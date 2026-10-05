"""Content-backed rules for the three-realm dao echoes mainline."""

from __future__ import annotations

from typing import Mapping

from ..content import ContentBundle, ContentError, bundled_content
from .mainline import MainlineStageDefinition, mainline_definitions


DAO_ECHOES_STORY_KEY = "story.mainline.dao_echoes"
DAO_ECHOES_LANES = ("builder", "witness", "traveler")
DAO_ECHOES_LANE_ALIASES = {
    "builder": "builder",
    "witness": "witness",
    "traveler": "traveler",
}

DaoEchoesStage = MainlineStageDefinition


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def dao_echoes_definitions(content: ContentBundle | None = None) -> tuple[DaoEchoesStage, ...]:
    """Load and validate the complete three-lane story contract."""

    definitions = mainline_definitions(_bundle(content), story_key=DAO_ECHOES_STORY_KEY)
    if len(definitions) != 30:
        raise ContentError("dao echoes must contain exactly 30 stages")
    by_lane: dict[str, list[DaoEchoesStage]] = {lane: [] for lane in DAO_ECHOES_LANES}
    labels: dict[str, str] = {}
    for definition in definitions:
        lane = definition.lane
        if lane not in by_lane:
            raise ContentError(f"dao echoes stage {definition.key} has an unsupported lane")
        if definition.chapter != 1 or definition.required_realm != "void_refining" or definition.required_layer != 10:
            raise ContentError(f"dao echoes stage {definition.key} has an invalid qualification")
        if not definition.lane_label:
            raise ContentError(f"dao echoes lane {lane} requires a display name")
        previous = labels.setdefault(lane, definition.lane_label)
        if previous != definition.lane_label:
            raise ContentError(f"dao echoes lane {lane} has inconsistent display names")
        reward = definition.first_clear_reward_map()
        if set(reward) != {definition.codex_flag} or reward[definition.codex_flag] != 1:
            raise ContentError(f"dao echoes stage {definition.key} must grant one codex flag")
        if definition.repeat_reward_map():
            raise ContentError(f"dao echoes stage {definition.key} cannot grant repeat rewards")
        by_lane[lane].append(definition)

    ordered: list[DaoEchoesStage] = []
    for lane in DAO_ECHOES_LANES:
        stages = sorted(by_lane[lane], key=lambda item: item.stage)
        if [stage.stage for stage in stages] != list(range(1, 11)):
            raise ContentError(f"dao echoes lane {lane} must contain stages 1 through 10")
        for index, stage in enumerate(stages):
            expected_key = f"lane.{lane}.chapter.{index + 1:02d}"
            if stage.key != expected_key:
                raise ContentError(f"dao echoes stage key is not closed: {stage.key}")
            expected_prerequisites = () if index == 0 else (f"lane.{lane}.chapter.{index:02d}",)
            if stage.prerequisites != expected_prerequisites:
                raise ContentError(f"dao echoes stage {stage.key} has invalid lane order")
        ordered.extend(stages)
    return tuple(ordered)


def dao_echoes_lane_labels(content: ContentBundle | None = None) -> Mapping[str, str]:
    labels: dict[str, str] = {}
    for definition in dao_echoes_definitions(content):
        labels.setdefault(definition.lane or "", definition.lane_label or "")
    return labels


def resolve_dao_echoes_lane(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = str(value).strip().casefold()
    aliases = dict(DAO_ECHOES_LANE_ALIASES)
    for lane, label in dao_echoes_lane_labels(content).items():
        aliases[label] = lane
    return aliases.get(normalized) or aliases.get(str(value).strip())


def dao_echoes_definition(
    lane: str,
    stage: int | str,
    content: ContentBundle | None = None,
) -> DaoEchoesStage:
    canonical_lane = resolve_dao_echoes_lane(lane, content)
    if canonical_lane is None:
        raise ValueError(f"unsupported dao echoes lane: {lane}")
    try:
        number = int(stage)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported dao echoes stage: {stage}") from exc
    if isinstance(stage, bool) or number < 1 or number > 10 or str(stage).strip() not in {str(number), f"{number:02d}"}:
        raise ValueError(f"unsupported dao echoes stage: {stage}")
    key = f"lane.{canonical_lane}.chapter.{number:02d}"
    try:
        return next(item for item in dao_echoes_definitions(content) if item.key == key)
    except StopIteration as exc:
        raise ValueError(f"unsupported dao echoes stage: {stage}") from exc


__all__ = [
    "DAO_ECHOES_LANES",
    "DAO_ECHOES_STORY_KEY",
    "DaoEchoesStage",
    "dao_echoes_definition",
    "dao_echoes_definitions",
    "dao_echoes_lane_labels",
    "resolve_dao_echoes_lane",
]
