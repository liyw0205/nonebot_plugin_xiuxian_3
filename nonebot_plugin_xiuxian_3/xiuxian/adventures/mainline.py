"""内容驱动的主线规则与解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from ..content import ContentBundle, ContentError, bundled_content
from ..routine.rules import honor_title


MAINLINE_STORY_KEY = "story.mainline.xuantian"
DOMAIN_FRONTIER_STORY_KEY = "story.mainline.domain_frontier"
MAINLINE_TOWN_COMMISSION_DELIVERED = "livelihood.town_commission.delivered"

MAINLINE_LOCKED = "locked"
MAINLINE_AVAILABLE = "available"
MAINLINE_RUNNING = "running"
MAINLINE_CLEARED = "cleared"
MAINLINE_REWARD_PENDING = "reward_pending"
MAINLINE_CLAIMED = "claimed"
MAINLINE_STATUSES = (
    MAINLINE_LOCKED,
    MAINLINE_AVAILABLE,
    MAINLINE_RUNNING,
    MAINLINE_CLEARED,
    MAINLINE_REWARD_PENDING,
    MAINLINE_CLAIMED,
)

_DEFAULT_CONTENT = bundled_content()


@dataclass(frozen=True, slots=True)
class MainlineStageDefinition:
    key: str
    story_key: str
    chapter: int
    stage: int
    label: str
    description: str
    prerequisites: tuple[str, ...]
    alternative_prerequisites: tuple[str, ...] = ()
    required_realm: str | None = None
    required_layer: int = 0
    first_clear_reward: tuple[tuple[str, int | str], ...] = ()
    repeat_reward: tuple[tuple[str, int | str], ...] = ()
    runtime_status: str = "open"
    aliases: tuple[str, ...] = ()
    reputation_key: str | None = None

    def first_clear_reward_map(self) -> dict[str, int | str]:
        return dict(self.first_clear_reward)

    def repeat_reward_map(self) -> dict[str, int | str]:
        return dict(self.repeat_reward)


MainlineDefinition = MainlineStageDefinition


MAINLINE_FORBIDDEN_REWARD_KEYS = frozenset(
    {
        "path_key",
        "selected_path",
        "ending_state",
        "ascension_ending",
        "ascension_merit",
        "world_merit",
        "realm_key",
        "realm_layer",
        "realm_cultivation",
        "cultivation",
        "total_cultivation",
        "foundation_quality",
        "breakthrough_preparation",
        "breakthrough_pity_bp",
        "dao_fruit",
        "tribulation_debt",
    }
)
MAINLINE_REWARD_PREFIXES = ("item.", "access.", "codex.")
MAINLINE_NUMERIC_REWARD_KEYS = frozenset(
    {"spirit_stones", "local_reputation", "service_reputation"}
)


def _content(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else _DEFAULT_CONTENT


def _string_tuple(value: object, field: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContentError(f"mainline {key} {field} must be a string list")
    return tuple(str(item).strip() for item in value)


def _reward_map(bundle: ContentBundle, value: object, field: str, key: str) -> tuple[tuple[str, int | str], ...]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"mainline {key} {field} must be a non-empty object")
    result: list[tuple[str, int | str]] = []
    for reward_key, reward_value in value.items():
        if not isinstance(reward_key, str) or not reward_key:
            raise ContentError(f"mainline {key} {field} contains an invalid reward key")
        if isinstance(reward_value, bool) or not isinstance(reward_value, (int, str)):
            raise ContentError(f"mainline {key} {field}.{reward_key} has an invalid value")
        if reward_key == "title_key":
            if not isinstance(reward_value, str) or not reward_value.strip():
                raise ContentError(f"mainline {key} {field}.{reward_key} must be a non-empty string")
        elif reward_key in MAINLINE_NUMERIC_REWARD_KEYS or (
            reward_key.startswith(MAINLINE_REWARD_PREFIXES)
            and reward_key not in MAINLINE_REWARD_PREFIXES
        ):
            if not isinstance(reward_value, int) or reward_value <= 0:
                raise ContentError(f"mainline {key} {field}.{reward_key} must be a positive integer")
        else:
            raise ContentError(f"mainline {key} contains unsupported reward {reward_key}")
        if reward_key in MAINLINE_FORBIDDEN_REWARD_KEYS:
            raise ContentError(f"mainline {key} contains forbidden reward {reward_key}")
        if reward_key.startswith("item."):
            try:
                bundle.require("item", reward_key, include_locked=False)
            except KeyError as exc:
                raise ContentError(f"mainline {key} references unknown item {reward_key}") from exc
        if reward_key == "title_key":
            if not isinstance(reward_value, str):
                raise ContentError(f"mainline {key} title_key must be a string")
            try:
                honor_title(reward_value)
            except ValueError as exc:
                raise ContentError(f"mainline {key} references unknown title {reward_value}") from exc
        if reward_key.startswith("codex.") and bundle.get("codex_entry", reward_key, include_locked=False) is None:
            if reward_key != "codex.observation":
                raise ContentError(f"mainline {key} references unknown codex entry {reward_key}")
        result.append((reward_key, reward_value))
    return tuple(result)


def mainline_definitions(
    content: ContentBundle | None = None,
    *,
    story_key: str | None = None,
) -> tuple[MainlineStageDefinition, ...]:
    """Parse and validate all mainline stages from the current content bundle."""

    bundle = _content(content)
    rows = bundle.list("mainline", include_locked=True)
    definitions: list[MainlineStageDefinition] = []
    for row in rows:
        key = row.get("key")
        if not isinstance(key, str) or not key:
            raise ContentError("mainline record requires key")
        record_story_key = row.get("story_key")
        if not isinstance(record_story_key, str) or not record_story_key.strip():
            raise ContentError(f"mainline {key} requires story_key")
        if story_key is not None and record_story_key != story_key:
            continue
        chapter = row.get("chapter")
        stage = row.get("stage")
        if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
            raise ContentError(f"mainline {key} chapter must be a positive integer")
        if isinstance(stage, bool) or not isinstance(stage, int) or stage < 1:
            raise ContentError(f"mainline {key} stage must be a positive integer")
        name = row.get("name")
        description = row.get("desc")
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
            raise ContentError(f"mainline {key} requires name and desc")
        prerequisites = _string_tuple(row.get("prerequisites", []), "prerequisites", key)
        alternatives = _string_tuple(row.get("alternative_prerequisites", []), "alternative_prerequisites", key)
        required_realm = row.get("required_realm")
        if required_realm is not None:
            if not isinstance(required_realm, str) or not required_realm:
                raise ContentError(f"mainline {key} required_realm must be a string")
            try:
                bundle.require("realm", required_realm, include_locked=False)
            except KeyError as exc:
                raise ContentError(f"mainline {key} references unknown realm {required_realm}") from exc
        required_layer = row.get("required_layer", 0)
        if isinstance(required_layer, bool) or not isinstance(required_layer, int) or required_layer < 0:
            raise ContentError(f"mainline {key} required_layer must be a non-negative integer")
        aliases = _string_tuple(row.get("aliases", []), "aliases", key)
        runtime_status = row.get("status", "locked")
        if runtime_status not in {"open", "active", "locked"}:
            raise ContentError(f"mainline {key} has unsupported status {runtime_status}")
        reputation_key = row.get("reputation_key")
        if reputation_key is not None and (not isinstance(reputation_key, str) or not reputation_key.strip()):
            raise ContentError(f"mainline {key} reputation_key must be a non-empty string")
        first_clear_reward = _reward_map(bundle, row.get("first_clear_reward"), "first_clear_reward", key)
        repeat_reward = _reward_map(bundle, row.get("repeat_reward"), "repeat_reward", key)
        if ("local_reputation" in dict(first_clear_reward) or "local_reputation" in dict(repeat_reward)) and reputation_key is None:
            raise ContentError(f"mainline {key} requires reputation_key for local_reputation")
        definitions.append(
            MainlineStageDefinition(
                key=key,
                story_key=record_story_key,
                chapter=chapter,
                stage=stage,
                label=name.strip(),
                description=description.strip(),
                prerequisites=prerequisites,
                alternative_prerequisites=alternatives,
                required_realm=required_realm,
                required_layer=required_layer,
                first_clear_reward=first_clear_reward,
                repeat_reward=repeat_reward,
                runtime_status="open" if runtime_status == "active" else str(runtime_status),
                aliases=aliases,
                reputation_key=reputation_key,
            )
        )
    definitions.sort(key=lambda item: (item.chapter, item.stage, item.key))
    if not definitions:
        scope = f" for {story_key}" if story_key else ""
        raise ContentError(f"mainline content must contain at least one stage{scope}")
    keys = {item.key for item in definitions}
    aliases: set[str] = set()
    for definition in definitions:
        for prerequisite in definition.prerequisites:
            if prerequisite.startswith("chapter.") and prerequisite not in keys:
                raise ContentError(f"mainline {definition.key} references unknown prerequisite {prerequisite}")
        for alias in definition.aliases:
            if alias in keys:
                raise ContentError(f"mainline alias conflicts with stage key {alias}")
            if alias in aliases:
                raise ContentError(f"duplicate mainline alias {alias}")
            aliases.add(alias)
    return tuple(definitions)


MAINLINE_STAGES = mainline_definitions(story_key=MAINLINE_STORY_KEY)
MAINLINE_STAGE_COUNT = len(MAINLINE_STAGES)
MAINLINE_DEFINITIONS: Mapping[str, MainlineStageDefinition] = {
    definition.key: definition for definition in MAINLINE_STAGES
}
DEFINITIONS = MAINLINE_DEFINITIONS
MAINLINE_ALIASES: Mapping[str, str] = {
    alias: definition.key for definition in MAINLINE_STAGES for alias in definition.aliases
}


def _stage_key(
    value: str | int,
    chapter: int = 1,
    *,
    story_key: str | None = MAINLINE_STORY_KEY,
    content: ContentBundle | None = None,
) -> str:
    if isinstance(value, bool):
        raise ValueError("mainline stage must be an integer or stable key")
    definitions = mainline_definitions(content, story_key=story_key)
    aliases = {alias: definition.key for definition in definitions for alias in definition.aliases}
    if isinstance(value, int):
        return f"chapter.{int(chapter)}.stage.{value}"
    candidate = str(value).strip()
    if candidate in aliases:
        return aliases[candidate]
    if candidate.isdigit():
        return f"chapter.{int(chapter)}.stage.{int(candidate)}"
    if story_key and candidate.startswith(f"{story_key}:"):
        candidate = candidate.split(":", 1)[1]
        parts = candidate.split(":")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            candidate = f"chapter.{parts[0]}.stage.{parts[1]}"
    return candidate


def mainline_stage_key(chapter: int, stage: int) -> str:
    if isinstance(chapter, bool) or isinstance(stage, bool) or int(chapter) < 1 or int(stage) < 1:
        raise ValueError("chapter and stage must be positive integers")
    return f"chapter.{int(chapter)}.stage.{int(stage)}"


def mainline_first_clear_key(
    chapter: int,
    stage: int,
    player_id: str,
    *,
    story_key: str = MAINLINE_STORY_KEY,
) -> str:
    if isinstance(chapter, bool) or isinstance(stage, bool) or not str(player_id):
        raise ValueError("chapter, stage and player_id are required")
    if not isinstance(story_key, str) or not story_key.strip():
        raise ValueError("story_key is required")
    return f"{story_key}:{int(chapter)}:{int(stage)}:{player_id}"


def resolve_mainline(
    value: str | int,
    *,
    chapter: int = 1,
    story_key: str | None = MAINLINE_STORY_KEY,
    content: ContentBundle | None = None,
) -> str | None:
    key = _stage_key(value, chapter, story_key=story_key, content=content)
    return key if key in {item.key for item in mainline_definitions(content, story_key=story_key)} else None


def mainline_definition(
    value: str | int,
    *,
    chapter: int = 1,
    story_key: str | None = MAINLINE_STORY_KEY,
    content: ContentBundle | None = None,
) -> MainlineStageDefinition:
    key = _stage_key(value, chapter, story_key=story_key, content=content)
    definitions = {item.key: item for item in mainline_definitions(content, story_key=story_key)}
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported mainline stage: {value}") from exc


def mainline_stage(
    stage: int,
    *,
    chapter: int = 1,
    story_key: str | None = MAINLINE_STORY_KEY,
    content: ContentBundle | None = None,
) -> MainlineStageDefinition:
    return mainline_definition(stage, chapter=chapter, story_key=story_key, content=content)


def _contains_stage(values: Iterable[str], key: str, content: ContentBundle | None = None) -> bool:
    target = _stage_key(key, story_key=None, content=content)
    return target in {_stage_key(str(value), story_key=None, content=content) for value in values}


def realm_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    row = _content(content).get("realm", str(realm_key))
    if row is None or not isinstance(row.get("rank"), int) or isinstance(row.get("rank"), bool):
        return -1
    return int(row["rank"])


def meets_realm(
    realm_key: str | None,
    layer: int,
    required_realm: str | None,
    required_layer: int,
    content: ContentBundle | None = None,
) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(str(realm_key), content), int(layer)) >= (
        realm_rank(required_realm, content),
        int(required_layer),
    )


def mainline_prerequisites_met(
    value: str | int | MainlineStageDefinition,
    state: Mapping[str, object] | None = None,
    *,
    completed_stages: Iterable[str] = (),
    completed_events: Iterable[str] = (),
    flags: Iterable[str] = (),
    realm_key: str | None = None,
    realm_layer: int = 0,
    content: ContentBundle | None = None,
) -> bool:
    if state is not None:
        completed_stages = state.get("completed_stages", completed_stages)  # type: ignore[assignment]
        completed_events = state.get("completed_events", completed_events)  # type: ignore[assignment]
        flags = state.get("flags", flags)  # type: ignore[assignment]
        realm_key = state.get("realm_key", realm_key)  # type: ignore[assignment]
        realm_layer = state.get("realm_layer", realm_layer)  # type: ignore[assignment]
    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value, content=content)
    stages = tuple(str(item) for item in completed_stages)
    events = {str(item) for item in completed_events}
    events.update(str(item) for item in flags)
    stage_keys = {item.key for item in mainline_definitions(content, story_key=definition.story_key)}
    for prerequisite in definition.prerequisites:
        if prerequisite.startswith("chapter.") or prerequisite in stage_keys:
            if not _contains_stage(stages, prerequisite, content):
                return False
        elif prerequisite not in events:
            return False
    if definition.alternative_prerequisites:
        has_alternative_event = any(item in events for item in definition.alternative_prerequisites)
        has_realm = meets_realm(
            realm_key,
            int(realm_layer),
            definition.required_realm,
            definition.required_layer,
            content,
        )
        if not (has_alternative_event or has_realm):
            return False
    elif not meets_realm(
        realm_key,
        int(realm_layer),
        definition.required_realm,
        definition.required_layer,
        content,
    ):
        return False
    return definition.runtime_status == "open"


def mainline_stage_status(
    value: str | int | MainlineStageDefinition,
    *,
    prerequisites_met: bool = False,
    running: bool = False,
    cleared: bool = False,
    reward_pending: bool = False,
    claimed: bool = False,
    content: ContentBundle | None = None,
) -> str:
    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value, content=content)
    if definition.runtime_status != "open":
        return MAINLINE_LOCKED
    if claimed:
        return MAINLINE_CLAIMED
    if reward_pending:
        return MAINLINE_REWARD_PENDING
    if cleared:
        return MAINLINE_CLEARED
    if running:
        return MAINLINE_RUNNING
    return MAINLINE_AVAILABLE if prerequisites_met else MAINLINE_LOCKED


def _checked_reward(reward: Mapping[str, int | str]) -> dict[str, int | str]:
    result = {str(key): value if isinstance(value, str) else int(value) for key, value in reward.items()}
    forbidden = MAINLINE_FORBIDDEN_REWARD_KEYS.intersection(result)
    if forbidden:
        raise ValueError(f"mainline reward contains forbidden keys: {sorted(forbidden)}")
    return result


def mainline_reward(
    value: str | int | MainlineStageDefinition,
    *,
    first_clear: bool = True,
    content: ContentBundle | None = None,
) -> dict[str, int | str]:
    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value, content=content)
    reward = definition.first_clear_reward_map() if first_clear else definition.repeat_reward_map()
    return _checked_reward(reward)


def mainline_first_clear_reward(value: str | int | MainlineStageDefinition, *, content: ContentBundle | None = None) -> dict[str, int | str]:
    return mainline_reward(value, first_clear=True, content=content)


def mainline_repeat_reward(value: str | int | MainlineStageDefinition, *, content: ContentBundle | None = None) -> dict[str, int | str]:
    return mainline_reward(value, first_clear=False, content=content)


def reward_map(definition: MainlineStageDefinition) -> dict[str, int | str]:
    return mainline_first_clear_reward(definition)


mainline_stage_definition = mainline_definition
mainline_status = mainline_stage_status
mainline_prerequisite_met = mainline_prerequisites_met


__all__ = [
    "DEFINITIONS",
    "MAINLINE_ALIASES",
    "MAINLINE_AVAILABLE",
    "MAINLINE_CLAIMED",
    "MAINLINE_CLEARED",
    "MAINLINE_DEFINITIONS",
    "MAINLINE_FORBIDDEN_REWARD_KEYS",
    "MAINLINE_NUMERIC_REWARD_KEYS",
    "MAINLINE_REWARD_PREFIXES",
    "MAINLINE_LOCKED",
    "MAINLINE_REWARD_PENDING",
    "MAINLINE_RUNNING",
    "MAINLINE_STAGE_COUNT",
    "MAINLINE_STAGES",
    "MAINLINE_STATUSES",
    "MAINLINE_STORY_KEY",
    "DOMAIN_FRONTIER_STORY_KEY",
    "MAINLINE_TOWN_COMMISSION_DELIVERED",
    "MainlineDefinition",
    "MainlineStageDefinition",
    "mainline_definition",
    "mainline_definitions",
    "mainline_first_clear_key",
    "mainline_first_clear_reward",
    "mainline_prerequisite_met",
    "mainline_prerequisites_met",
    "mainline_repeat_reward",
    "mainline_reward",
    "mainline_stage",
    "mainline_stage_definition",
    "mainline_stage_key",
    "mainline_stage_status",
    "mainline_status",
    "meets_realm",
    "realm_rank",
    "resolve_mainline",
    "reward_map",
]
