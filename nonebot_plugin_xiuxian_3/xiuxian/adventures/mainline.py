"""Pure, versioned rules for the v0.1 Xuantian mainline.

This module describes the v0.1 story contract.  Chapter one contains the
open runtime stages; the documented chapter-two town commission remains
explicitly closed until its persistent commission domain is available.  It
does not advance a player, persist a run, or grant rewards; those concerns
belong to the application/repository and reward services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


MAINLINE_STORY_KEY = "story.mainline.xuantian"
MAINLINE_CONTENT_VERSION = "content-0.1"
MAINLINE_RULE_VERSION = "mainline-0.1.0"
RULE_VERSION = "adventures-0.1.0"
CONTENT_VERSION = MAINLINE_CONTENT_VERSION

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
    content_version: str = MAINLINE_CONTENT_VERSION
    rule_version: str = MAINLINE_RULE_VERSION

    def first_clear_reward_map(self) -> dict[str, int | str]:
        return {str(key): value if isinstance(value, str) else int(value) for key, value in self.first_clear_reward}

    def repeat_reward_map(self) -> dict[str, int | str]:
        return {str(key): value if isinstance(value, str) else int(value) for key, value in self.repeat_reward}


# Keep a short definition name available alongside the explicit stage name.
MainlineDefinition = MainlineStageDefinition


MAINLINE_STAGES: tuple[MainlineStageDefinition, ...] = (
    MainlineStageDefinition(
        key="chapter.1.stage.1",
        story_key=MAINLINE_STORY_KEY,
        chapter=1,
        stage=1,
        label="初入玄天",
        description="完成寻仙问道，踏入玄天近郊。",
        prerequisites=("player.start_seeking",),
        first_clear_reward=(
            ("access.xuantian.outskirts", 1),
            ("codex.place.outskirts", 1),
            ("local_reputation", 3),
        ),
        repeat_reward=(("spirit_stones", 5),),
    ),
    MainlineStageDefinition(
        key="chapter.1.stage.2",
        story_key=MAINLINE_STORY_KEY,
        chapter=1,
        stage=2,
        label="灵泉取叶",
        description="沿近郊线索前往灵泉谷，取得第一片灵叶。",
        prerequisites=("chapter.1.stage.1",),
        alternative_prerequisites=("guide.gather_blood_grass",),
        required_realm="qi_sensing",
        required_layer=1,
        first_clear_reward=(
            ("access.xuantian.spirit_field", 1),
            ("item.herb.spirit_leaf", 2),
        ),
        repeat_reward=(("item.herb.spirit_leaf", 1),),
    ),
    MainlineStageDefinition(
        key="chapter.1.stage.3",
        story_key=MAINLINE_STORY_KEY,
        chapter=1,
        stage=3,
        label="雾中守门",
        description="在雾隐入口完成守门试炼，取得秘境线索。",
        prerequisites=("chapter.1.stage.2",),
        required_realm="qi_sensing",
        required_layer=3,
        first_clear_reward=(
            ("access.instance.secret_realm", 1),
            ("title_key", "title.mist_watcher"),
        ),
        repeat_reward=(("codex.observation", 1),),
    ),
    MainlineStageDefinition(
        key="chapter.2.stage.1",
        story_key=MAINLINE_STORY_KEY,
        chapter=2,
        stage=1,
        label="城镇委托",
        description="完成一项常驻经营委托，开启玄天商路。",
        prerequisites=("chapter.1.stage.3",),
        first_clear_reward=(
            ("access.xuantian.trade_route", 1),
            ("service_reputation", 5),
        ),
        repeat_reward=(("spirit_stones", 10),),
        runtime_status="closed",
    ),
)
MAINLINE_STAGE_COUNT = len(MAINLINE_STAGES)

MAINLINE_DEFINITIONS: Mapping[str, MainlineStageDefinition] = {
    definition.key: definition for definition in MAINLINE_STAGES
}
DEFINITIONS = MAINLINE_DEFINITIONS

MAINLINE_ALIASES: Mapping[str, str] = {
    "初入玄天": "chapter.1.stage.1",
    "灵泉取叶": "chapter.1.stage.2",
    "雾中守门": "chapter.1.stage.3",
    "城镇委托": "chapter.2.stage.1",
}

_REALM_RANK = {
    "mortal": 0,
    "qi_sensing": 1,
    "qi_gathering": 2,
    "foundation": 3,
    "golden_core": 4,
    "nascent_soul": 5,
}

# Mainline v0.1 is intentionally limited to ordinary progression/display
# assets.  Keeping this guard next to the content table makes accidental
# introduction of path or ending state visible during module import/tests.
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


def _stage_key(value: str | int, chapter: int = 1) -> str:
    if isinstance(value, bool):
        raise ValueError("mainline stage must be an integer or stable key")
    if isinstance(value, int):
        return f"chapter.{int(chapter)}.stage.{value}"
    candidate = str(value).strip()
    if candidate in MAINLINE_ALIASES:
        return MAINLINE_ALIASES[candidate]
    if candidate.isdigit():
        return f"chapter.{int(chapter)}.stage.{int(candidate)}"
    if candidate.startswith(f"{MAINLINE_STORY_KEY}:"):
        candidate = candidate.split(":", 1)[1]
        parts = candidate.split(":")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            candidate = f"chapter.{parts[0]}.stage.{parts[1]}"
    return candidate


def mainline_stage_key(chapter: int, stage: int) -> str:
    """Return the stable chapter/stage key used by snapshots and operations."""

    if isinstance(chapter, bool) or isinstance(stage, bool):
        raise ValueError("chapter and stage must be positive integers")
    if int(chapter) < 1 or int(stage) < 1:
        raise ValueError("chapter and stage must be positive")
    return f"chapter.{int(chapter)}.stage.{int(stage)}"


def mainline_first_clear_key(chapter: int, stage: int, player_id: str) -> str:
    """Return the per-player idempotency key for a first-clear reward."""

    if isinstance(chapter, bool) or isinstance(stage, bool):
        raise ValueError("chapter and stage must be positive integers")
    if not str(player_id):
        raise ValueError("player_id is required")
    return f"{MAINLINE_STORY_KEY}:{int(chapter)}:{int(stage)}:{player_id}"


def resolve_mainline(value: str | int, *, chapter: int = 1) -> str | None:
    key = _stage_key(value, chapter)
    return key if key in MAINLINE_DEFINITIONS else None


def mainline_definition(value: str | int, *, chapter: int = 1) -> MainlineStageDefinition:
    key = _stage_key(value, chapter)
    try:
        return MAINLINE_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported mainline stage: {value}") from exc


def mainline_stage(stage: int, *, chapter: int = 1) -> MainlineStageDefinition:
    return mainline_definition(stage, chapter=chapter)


def _contains_stage(values: Iterable[str], key: str) -> bool:
    target = _stage_key(key)
    return any(_stage_key(str(value)) == target for value in values)


def realm_rank(realm_key: str) -> int:
    return _REALM_RANK.get(str(realm_key), -1)


def meets_realm(realm_key: str | None, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(str(realm_key)), int(layer)) >= (
        realm_rank(required_realm),
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
) -> bool:
    """Evaluate the v0.1 prerequisite snapshot without touching persistence."""

    if state is not None:
        completed_stages = state.get("completed_stages", completed_stages)  # type: ignore[assignment]
        completed_events = state.get("completed_events", completed_events)  # type: ignore[assignment]
        flags = state.get("flags", flags)  # type: ignore[assignment]
        realm_key = state.get("realm_key", realm_key)  # type: ignore[assignment]
        realm_layer = state.get("realm_layer", realm_layer)  # type: ignore[assignment]
    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value)
    stages = tuple(str(item) for item in completed_stages)
    events = {str(item) for item in completed_events}
    events.update(str(item) for item in flags)

    for prerequisite in definition.prerequisites:
        if prerequisite.startswith("chapter."):
            if not _contains_stage(stages, prerequisite):
                return False
        elif prerequisite not in events:
            return False

    # Stage 2 accepts either the qi-sensing threshold or the completed mortal
    # gathering lesson.  Stage 3 has only the qi-sensing threshold.
    if definition.alternative_prerequisites:
        has_alternative_event = any(item in events for item in definition.alternative_prerequisites)
        has_realm = meets_realm(
            realm_key,
            realm_layer,
            definition.required_realm,
            definition.required_layer,
        )
        if not (has_alternative_event or has_realm):
            return False
    elif not meets_realm(
        realm_key,
        realm_layer,
        definition.required_realm,
        definition.required_layer,
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
) -> str:
    """Project a run snapshot into the documented mainline state machine."""

    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value)
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
    result = {
        str(key): value if isinstance(value, str) else int(value)
        for key, value in reward.items()
    }
    forbidden = MAINLINE_FORBIDDEN_REWARD_KEYS.intersection(result)
    if forbidden:
        raise ValueError(f"mainline reward contains forbidden keys: {sorted(forbidden)}")
    return result


def mainline_reward(value: str | int | MainlineStageDefinition, *, first_clear: bool = True) -> dict[str, int | str]:
    definition = value if isinstance(value, MainlineStageDefinition) else mainline_definition(value)
    reward = definition.first_clear_reward_map() if first_clear else definition.repeat_reward_map()
    return _checked_reward(reward)


def mainline_first_clear_reward(value: str | int | MainlineStageDefinition) -> dict[str, int | str]:
    return mainline_reward(value, first_clear=True)


def mainline_repeat_reward(value: str | int | MainlineStageDefinition) -> dict[str, int | str]:
    return mainline_reward(value, first_clear=False)


def reward_map(definition: MainlineStageDefinition) -> dict[str, int | str]:
    return mainline_first_clear_reward(definition)


# Naming aliases keep the rules module convenient for callers that use the
# existing ``*_definition`` naming convention in other adventure modules.
mainline_stage_definition = mainline_definition
mainline_status = mainline_stage_status
mainline_prerequisite_met = mainline_prerequisites_met


__all__ = [
    "CONTENT_VERSION",
    "DEFINITIONS",
    "MAINLINE_ALIASES",
    "MAINLINE_AVAILABLE",
    "MAINLINE_CLAIMED",
    "MAINLINE_CLEARED",
    "MAINLINE_CONTENT_VERSION",
    "MAINLINE_DEFINITIONS",
    "MAINLINE_FORBIDDEN_REWARD_KEYS",
    "MAINLINE_LOCKED",
    "MAINLINE_REWARD_PENDING",
    "MAINLINE_RULE_VERSION",
    "MAINLINE_RUNNING",
    "MAINLINE_STATUSES",
    "MAINLINE_STAGES",
    "MAINLINE_STAGE_COUNT",
    "MAINLINE_STORY_KEY",
    "MainlineDefinition",
    "MainlineStageDefinition",
    "RULE_VERSION",
    "mainline_definition",
    "mainline_first_clear_key",
    "mainline_first_clear_reward",
    "mainline_prerequisites_met",
    "mainline_prerequisite_met",
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
