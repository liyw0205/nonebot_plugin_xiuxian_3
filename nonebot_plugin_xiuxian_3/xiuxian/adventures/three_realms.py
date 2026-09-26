"""Versioned content for the Yuan-ying three-realms mainline."""

from __future__ import annotations

from dataclasses import dataclass


THREE_REALMS_STORY_KEY = "story.mainline.three_realms"
THREE_REALMS_CONTENT_VERSION = "content-0.3"
THREE_REALMS_RULE_VERSION = "adventures-0.3.0"
THREE_REALMS_LANES = ("mediation", "contract", "symbiosis")
THREE_REALMS_LANE_LABELS = {
    "mediation": "调停",
    "contract": "契约",
    "symbiosis": "共生",
}
THREE_REALMS_LANE_ALIASES = {
    "mediation": "mediation",
    "调停": "mediation",
    "contract": "contract",
    "契约": "contract",
    "symbiosis": "symbiosis",
    "共生": "symbiosis",
}
THREE_REALMS_LANE_FACTIONS = {
    "mediation": "xuantian",
    "contract": "demon",
    "symbiosis": "beast",
}


@dataclass(frozen=True, slots=True)
class ThreeRealmsStage:
    key: str
    lane: str
    stage: int
    label: str
    description: str
    codex_flag: str
    prerequisites: tuple[str, ...] = ()
    content_version: str = THREE_REALMS_CONTENT_VERSION
    rule_version: str = THREE_REALMS_RULE_VERSION
    runtime_status: str = "open"


_STORY = {
    "mediation": (
        ("递交调停书", "你把三界各自的诉求整理成可核验的调停书。"),
        ("厘清争端", "你区分事实、推测和传闻，避免用旧怨替代证据。"),
        ("主持会面", "你主持一次小规模会面，让三界代表先确认共同底线。"),
        ("保留异议", "你把未达成一致的部分写入记录，而不是强行宣布共识。"),
        ("立下界标", "三界共同确认新的边界记录，允许后来者继续修订。"),
    ),
    "contract": (
        ("核对旧约", "你逐条核对三界旧约，标出仍然有效与已经失效的条款。"),
        ("交换信物", "各方自愿交换可撤回的信物，确认契约不会转移私人资产。"),
        ("校验责任", "你把履约责任分配给签约方，并为违约留下可追溯证据。"),
        ("公开条款", "契约条款向三界公开，任何一方都能复核同一份版本。"),
        ("完成签印", "三界完成最终签印，正式开放界隙主线通行资格。"),
    ),
    "symbiosis": (
        ("记录共生点", "你记录三界可以互相补足的灵脉与资源节点。"),
        ("安排轮值", "三界共同制定轮值方案，避免任何一方独占维护责任。"),
        ("修复节点", "你与各界工匠修复一个共享节点，不取走源头资源。"),
        ("核验回报", "各方核验共享节点的回报与代价，保留失败方案。"),
        ("确认共生", "三界确认共生方案可以继续，也可以由后来者修改。"),
    ),
}


def _stage(lane: str, number: int) -> ThreeRealmsStage:
    label, description = _STORY[lane][number - 1]
    return ThreeRealmsStage(
        key=f"lane.{lane}.chapter.{number:02d}",
        lane=lane,
        stage=number,
        label=label,
        description=description,
        codex_flag=f"codex.story.three_realms.{lane}.chapter.{number:02d}",
        prerequisites=(f"lane.{lane}.chapter.{number - 1:02d}",) if number > 1 else (),
    )


THREE_REALMS_STAGES = tuple(
    _stage(lane, number)
    for lane in THREE_REALMS_LANES
    for number in range(1, 6)
)
THREE_REALMS_DEFINITIONS = {stage.key: stage for stage in THREE_REALMS_STAGES}


def resolve_three_realms_lane(value: str) -> str | None:
    raw = str(value).strip()
    return THREE_REALMS_LANE_ALIASES.get(raw.lower()) or THREE_REALMS_LANE_ALIASES.get(raw)


def three_realms_definition(lane: str, stage: int | str) -> ThreeRealmsStage:
    canonical_lane = resolve_three_realms_lane(lane)
    if canonical_lane is None:
        raise ValueError(f"unsupported three-realms lane: {lane}")
    try:
        number = int(stage)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported three-realms stage: {stage}") from exc
    if isinstance(stage, bool) or number < 1 or number > 5 or str(stage).strip() not in {str(number), f"{number:02d}"}:
        raise ValueError(f"unsupported three-realms stage: {stage}")
    return THREE_REALMS_DEFINITIONS[f"lane.{canonical_lane}.chapter.{number:02d}"]


__all__ = [
    "THREE_REALMS_CONTENT_VERSION",
    "THREE_REALMS_DEFINITIONS",
    "THREE_REALMS_LANE_FACTIONS",
    "THREE_REALMS_LANE_LABELS",
    "THREE_REALMS_LANES",
    "THREE_REALMS_RULE_VERSION",
    "THREE_REALMS_STAGES",
    "THREE_REALMS_STORY_KEY",
    "ThreeRealmsStage",
    "resolve_three_realms_lane",
    "three_realms_definition",
]
