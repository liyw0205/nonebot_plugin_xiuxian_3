"""Pure rules for the first cultivation loop."""

from __future__ import annotations

from collections.abc import Mapping

from .models import CultivationMode, LayerUnlock


REALM_QI_SENSING = "qi_sensing"
REALM_QI_GATHERING = "qi_gathering"
REALM_FOUNDATION = "foundation"
REALM_GOLDEN_CORE = "golden_core"
REALM_NASCENT_SOUL = "nascent_soul"
REALM_SOUL_TRANSFORMATION = "soul_transformation"
REALM_VOID_REFINING = "void_refining"
MODE_BREATHING = "cultivate.breathing"
MODE_SPIRIT_SPRING = "cultivate.spirit_spring"
RULE_VERSION = "progression-0.1.1"
SPIRIT_SPRING_RULE_VERSION = "progression-0.1.2"

# Index zero represents the L1 entry point. Values are the minimum realm
# cultivation required for each layer in the content-0.1 snapshot.
QI_SENSING_THRESHOLDS = (0, 80, 170, 280, 410, 560, 730, 920, 1130, 1360)
QI_GATHERING_THRESHOLDS = (0, 180, 380, 620, 900, 1220, 1580, 1980, 2420, 2900)
FOUNDATION_THRESHOLDS = (0, 420, 900, 1480, 2180, 3000, 3950, 5050, 6300, 7700)
GOLDEN_CORE_THRESHOLDS = (0, 2300, 5000, 8200, 12000, 17000, 23000, 30000, 38000, 47000)
NASCENT_SOUL_THRESHOLDS = (0, 9000, 19000, 32000, 48000, 68000, 92000, 120000, 153000, 190000)
SOUL_TRANSFORMATION_THRESHOLDS = (0, 28000, 60000, 100000, 150000, 210000, 285000, 375000, 480000, 600000)
VOID_REFINING_THRESHOLDS = (0, 90000, 200000, 340000, 520000, 740000, 1000000, 1320000, 1700000, 2150000)
REALM_THRESHOLDS = {
    REALM_QI_SENSING: QI_SENSING_THRESHOLDS,
    REALM_QI_GATHERING: QI_GATHERING_THRESHOLDS,
    REALM_FOUNDATION: FOUNDATION_THRESHOLDS,
    REALM_GOLDEN_CORE: GOLDEN_CORE_THRESHOLDS,
    REALM_NASCENT_SOUL: NASCENT_SOUL_THRESHOLDS,
    REALM_SOUL_TRANSFORMATION: SOUL_TRANSFORMATION_THRESHOLDS,
    REALM_VOID_REFINING: VOID_REFINING_THRESHOLDS,
}
FORMAL_REALMS = frozenset(REALM_THRESHOLDS)
BREATHING_STAMINA_COST = 2
BREATHING_DURATION_SECONDS = 10 * 60
BREATHING_BASE_CULTIVATION = 40
SPIRIT_SPRING_STAMINA_COST = 3
SPIRIT_SPRING_DURATION_SECONDS = 15 * 60
SPIRIT_SPRING_BASE_CULTIVATION = 70
SPIRIT_SPRING_ENVIRONMENT_BP = 11500
SPIRIT_SPRING_DAILY_LIMIT = 4
RECOVERY_PERIOD_SECONDS = 30 * 60
CULTIVATION_SETTLEMENT_GRACE_SECONDS = 24 * 60 * 60

SPIRIT_FIELD_LOCATION = "xuantian.spirit_field"
CULTIVATION_MODE_LABELS = {
    MODE_BREATHING: "调息修炼",
    MODE_SPIRIT_SPRING: "灵泉修炼",
}

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
    thresholds = REALM_THRESHOLDS.get(realm_key)
    if thresholds is None or layer < 1:
        return None
    next_layer = layer + 1
    if next_layer > 10:
        return None
    return thresholds[next_layer - 1]


def cultivation_mode(mode_key: str) -> CultivationMode:
    if mode_key == MODE_BREATHING:
        return CultivationMode(
            key=MODE_BREATHING,
            label=CULTIVATION_MODE_LABELS[MODE_BREATHING],
            stamina_cost=BREATHING_STAMINA_COST,
            duration_seconds=BREATHING_DURATION_SECONDS,
            base_cultivation=BREATHING_BASE_CULTIVATION,
            environment_bp=10000,
            daily_limit=None,
            rule_version=RULE_VERSION,
        )
    if mode_key == MODE_SPIRIT_SPRING:
        return CultivationMode(
            key=MODE_SPIRIT_SPRING,
            label=CULTIVATION_MODE_LABELS[MODE_SPIRIT_SPRING],
            stamina_cost=SPIRIT_SPRING_STAMINA_COST,
            duration_seconds=SPIRIT_SPRING_DURATION_SECONDS,
            base_cultivation=SPIRIT_SPRING_BASE_CULTIVATION,
            environment_bp=SPIRIT_SPRING_ENVIRONMENT_BP,
            daily_limit=SPIRIT_SPRING_DAILY_LIMIT,
            rule_version=SPIRIT_SPRING_RULE_VERSION,
            required_location=SPIRIT_FIELD_LOCATION,
        )
    raise ValueError(f"unsupported cultivation mode: {mode_key}")


def cultivation_mode_label(mode_key: str) -> str:
    return cultivation_mode(mode_key).label


def cultivation_gain(
    base: int,
    qualification: Mapping[str, int],
    *,
    environment_bp: int = 10000,
    state_bp: int = 10000,
) -> int:
    """Apply insight, environment and state multipliers using integer bp."""

    insight = max(0, int(qualification.get("insight", 0)))
    environment = max(0, int(environment_bp))
    state = max(0, int(state_bp))
    return (base * (200 + insight) * environment * state) // (200 * 10000 * 10000)


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
