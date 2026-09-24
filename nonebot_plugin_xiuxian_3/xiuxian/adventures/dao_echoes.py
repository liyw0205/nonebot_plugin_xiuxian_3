"""Versioned content for the v0.6 three-realm dao echoes mainline."""

from __future__ import annotations

from dataclasses import dataclass


DAO_ECHOES_STORY_KEY = "story.mainline.dao_echoes"
DAO_ECHOES_CONTENT_VERSION = "content-0.6"
DAO_ECHOES_RULE_VERSION = "adventures-0.6.0"
DAO_ECHOES_LANES = ("builder", "witness", "traveler")
DAO_ECHOES_LANE_LABELS = {
    "builder": "建设者",
    "witness": "见证者",
    "traveler": "远行者",
}
DAO_ECHOES_LANE_ALIASES = {
    "builder": "builder",
    "建设者": "builder",
    "witness": "witness",
    "见证者": "witness",
    "traveler": "traveler",
    "远行者": "traveler",
}


@dataclass(frozen=True, slots=True)
class DaoEchoesStage:
    key: str
    lane: str
    stage: int
    label: str
    description: str
    codex_flag: str
    prerequisites: tuple[str, ...] = ()
    content_version: str = DAO_ECHOES_CONTENT_VERSION
    rule_version: str = DAO_ECHOES_RULE_VERSION
    runtime_status: str = "open"


_STORY = {
    "builder": (
        ("检校旧碑", "你从玄天旧碑校正三界道路的刻痕。"),
        ("补绘河图", "你把魔界商路与玄天水脉补入共用地图。"),
        ("修复灵脉", "你记录妖界愿意开放的灵脉节点，不取走源头。"),
        ("搭建互市", "三界代表确认互市只交换自愿交付的物资。"),
        ("重立界标", "你为不同语言和习俗并存的边界立下新界标。"),
        ("补缀界壁", "你与各界工匠修补裂隙，不抹去旧有疆界。"),
        ("汇合三源", "三界各自交出一枚可撤回的道源校验印。"),
        ("立约共修", "你把维护责任分给三界，而非交给单一宗门。"),
        ("回望代价", "你登记工程代价与未解决的异议，供后来者查阅。"),
        ("道统新章", "三界共同确认工程可以延续，也可以由后人修改。"),
    ),
    "witness": (
        ("收录旧誓", "你收录三界旧约原文，不把互相矛盾的誓言删去。"),
        ("听取三界", "你分别记录玄天、魔界和妖界的陈述与诉求。"),
        ("辨清旧争", "你将争端中的事实、推测和传闻分开存档。"),
        ("见证守卫", "你记录一次边境防御的参与者与各方损失。"),
        ("见证互助", "你把一次跨界救援记为共同完成，而非单方恩赐。"),
        ("核验盟约", "你逐条核对盟约文本与实际履行记录。"),
        ("保留异议", "你为未签署盟约的意见保留同等可查的档案。"),
        ("确认代价", "你将停战与合作的代价写入公开记录。"),
        ("保存全录", "你完成三界档案副本，任何一界都可核验其內容。"),
        ("不替众人选择", "你把记录交还三界，不替任何人决定共同结局。"),
    ),
    "traveler": (
        ("走访玄天", "你从玄天出发，确认旧有道路仍可安全通行。"),
        ("渡过魔土", "你沿许可路线穿过魔界，记录沿途补给点。"),
        ("寻访妖庭", "你到访妖界聚落，依当地规矩递交来意。"),
        ("巡查界隙", "你巡查三界交界处，标记可通行与需避让的区域。"),
        ("抵达档案", "你把一路见闻交给虚空档案遗迹保存。"),
        ("重返三界", "你带回三地各自认可的路线副本。"),
        ("交接道路", "你向接任者说明沿途风险与通行约定。"),
        ("携行消息", "你传递各界允许公开的消息，不带走私密档案。"),
        ("拒绝捷径", "你放弃未经许可的捷径，保留可复核的行程。"),
        ("归来开篇", "你回到出发地，确认这条路由后来者继续书写。"),
    ),
}


def _stage(lane: str, number: int) -> DaoEchoesStage:
    label, description = _STORY[lane][number - 1]
    key = f"lane.{lane}.chapter.{number:02d}"
    prerequisites = (f"lane.{lane}.chapter.{number - 1:02d}",) if number > 1 else ()
    return DaoEchoesStage(
        key=key,
        lane=lane,
        stage=number,
        label=label,
        description=description,
        codex_flag=f"codex.story.dao_echoes.{lane}.chapter.{number:02d}",
        prerequisites=prerequisites,
    )


DAO_ECHOES_STAGES = tuple(
    _stage(lane, number)
    for lane in DAO_ECHOES_LANES
    for number in range(1, 11)
)
DAO_ECHOES_DEFINITIONS = {stage.key: stage for stage in DAO_ECHOES_STAGES}


def resolve_dao_echoes_lane(value: str) -> str | None:
    return DAO_ECHOES_LANE_ALIASES.get(str(value).strip().lower()) or DAO_ECHOES_LANE_ALIASES.get(str(value).strip())


def dao_echoes_definition(lane: str, stage: int | str) -> DaoEchoesStage:
    canonical_lane = resolve_dao_echoes_lane(lane)
    if canonical_lane is None:
        raise ValueError(f"unsupported dao echoes lane: {lane}")
    try:
        number = int(stage)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported dao echoes stage: {stage}") from exc
    if isinstance(stage, bool) or number < 1 or number > 10 or str(stage).strip() not in {str(number), f"{number:02d}"}:
        raise ValueError(f"unsupported dao echoes stage: {stage}")
    return DAO_ECHOES_DEFINITIONS[f"lane.{canonical_lane}.chapter.{number:02d}"]


__all__ = [
    "DAO_ECHOES_CONTENT_VERSION",
    "DAO_ECHOES_DEFINITIONS",
    "DAO_ECHOES_LANES",
    "DAO_ECHOES_LANE_LABELS",
    "DAO_ECHOES_RULE_VERSION",
    "DAO_ECHOES_STAGES",
    "DAO_ECHOES_STORY_KEY",
    "DaoEchoesStage",
    "dao_echoes_definition",
    "resolve_dao_echoes_lane",
]
