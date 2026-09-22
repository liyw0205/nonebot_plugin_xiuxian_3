"""Pure rules for the first cultivation loop."""

from __future__ import annotations

from collections.abc import Mapping

from .models import LayerUnlock


REALM_QI_SENSING = "qi_sensing"
MODE_BREATHING = "cultivate.breathing"
RULE_VERSION = "progression-0.1.1"

# Index zero represents the L1 entry point. Values are the minimum realm
# cultivation required for each layer in the content-0.1 snapshot.
QI_SENSING_THRESHOLDS = (0, 80, 170, 280, 410, 560, 730, 920, 1130, 1360)
BREATHING_STAMINA_COST = 2
BREATHING_DURATION_SECONDS = 10 * 60
BREATHING_BASE_CULTIVATION = 40
RECOVERY_PERIOD_SECONDS = 30 * 60
CULTIVATION_SETTLEMENT_GRACE_SECONDS = 24 * 60 * 60

# These are deliberately previews/qualifications, not direct access to future
# systems.  The application can expose them before the corresponding domain is
# implemented without accidentally opening a new write path.
QI_SENSING_LAYER_UNLOCKS: dict[int, tuple[LayerUnlock, ...]] = {
    3: (
        LayerUnlock(
            key="guidance.path",
            title="道途指导",
            description="可查看当前道途的进阶指导。",
            status="open",
        ),
        LayerUnlock(
            key="livelihood.service.second.preview",
            title="常驻经营第二类服务预览",
            description="可预览下一类常驻经营服务，正式承接将在对应玩法开放后解锁。",
        ),
    ),
    6: (
        LayerUnlock(
            key="cultivate.seclusion.preview",
            title="闭关修炼预览",
            description="可查看 `cultivate.seclusion` 的开放条件；聚气后才可执行。",
        ),
        LayerUnlock(
            key="sect.regular_task",
            title="宗门常规任务资格",
            description="获得宗门常规任务的资格提示。",
            status="open",
        ),
    ),
    9: (
        LayerUnlock(
            key="progression.breakthrough.preview",
            title="跨境突破预览",
            description="可查看下一境界的突破准备，但感气 L9 不能创建突破会话。",
        ),
        LayerUnlock(
            key="exploration.elite.preview",
            title="精英历练准备提示",
            description="可查看精英历练和洞天深层的准备要求。",
        ),
    ),
    10: (
        LayerUnlock(
            key="progression.cross_realm.preview",
            title="跨境突破资格预览",
            description="已达到感气混元，可检查聚气突破的材料、地点和状态条件。",
        ),
    ),
}


def next_layer_threshold(realm_key: str, layer: int) -> int | None:
    if realm_key != REALM_QI_SENSING or layer < 1:
        return None
    next_layer = layer + 1
    if next_layer > 10:
        return None
    return QI_SENSING_THRESHOLDS[next_layer - 1]


def cultivation_gain(base: int, qualification: Mapping[str, int]) -> int:
    """Apply the integer version of ``base * (1 + insight / 200)``."""

    insight = max(0, int(qualification.get("insight", 0)))
    return (base * (200 + insight)) // 200


def can_advance_layer(realm_key: str, layer: int, cultivation: int) -> bool:
    threshold = next_layer_threshold(realm_key, layer)
    return threshold is not None and cultivation >= threshold


def layer_unlocks(realm_key: str, layer: int) -> tuple[LayerUnlock, ...]:
    """Return milestone unlocks reached by entering ``layer``.

    Unlocks are derived from the destination layer and are therefore stable for
    a repeated operation.  Other realms are intentionally empty until their
    content snapshots define their own contracts.
    """

    if realm_key != REALM_QI_SENSING or layer < 1 or layer > 10:
        return ()
    return QI_SENSING_LAYER_UNLOCKS.get(layer, ())


unlocks_for_layer = layer_unlocks


def segment_for_layer(layer: int) -> str:
    """Return the display segment derived from a valid formal layer."""

    if layer < 1 or layer > 10:
        raise ValueError("formal realm layer must be between 1 and 10")
    if layer <= 3:
        return "入门"
    if layer <= 6:
        return "稳固"
    if layer <= 9:
        return "圆满"
    return "混元"
