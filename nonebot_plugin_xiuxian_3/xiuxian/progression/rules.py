"""Pure rules for the first cultivation loop."""

from __future__ import annotations


from collections.abc import Mapping

from ..content import ContentBundle, ContentError, bundled_content
from .models import CultivationMode, LayerUnlock


REALM_QI_SENSING = "qi_sensing"
REALM_QI_GATHERING = "qi_gathering"
REALM_FOUNDATION = "foundation"
REALM_GOLDEN_CORE = "golden_core"
REALM_NASCENT_SOUL = "nascent_soul"
REALM_SOUL_TRANSFORMATION = "soul_transformation"
REALM_VOID_REFINING = "void_refining"
REALM_DAO_UNION = "dao_union"
REALM_TRIBULATION = "tribulation"
MODE_BREATHING = "cultivate.breathing"
MODE_SPIRIT_SPRING = "cultivate.spirit_spring"
MODE_SECLUSION = "cultivate.seclusion"
MODE_SOUL_REFINEMENT = "cultivate.soul_refinement"

def _content_thresholds(
    content: ContentBundle | None = None,
) -> tuple[dict[str, tuple[int, ...]], dict[str, int]]:
    bundle = content or bundled_content()
    thresholds: dict[str, tuple[int, ...]] = {}
    max_layers: dict[str, int] = {}
    for row in bundle.list("realm", include_locked=False):
        key = row["key"]
        minimum = row.get("layer_min")
        maximum = row.get("layer_max")
        values = row.get("layer_thresholds")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum < 0
            or maximum < minimum
            or not isinstance(values, dict)
        ):
            raise ContentError(f"realm {key} has invalid layer range or thresholds")
        expected = {str(layer) for layer in range(minimum, maximum + 1)}
        if set(values) != expected:
            raise ContentError(f"realm {key} must configure thresholds for layers {sorted(expected)}")
        ordered = tuple(values[str(layer)] for layer in range(minimum, maximum + 1))
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in ordered):
            raise ContentError(f"realm {key} thresholds must be non-negative integers")
        thresholds[key] = ordered
        max_layers[key] = maximum
    if not thresholds:
        raise ContentError("content has no active realm records")
    return thresholds, max_layers


REALM_THRESHOLDS, REALM_MAX_LAYERS = _content_thresholds()
QI_SENSING_THRESHOLDS = REALM_THRESHOLDS[REALM_QI_SENSING]
QI_GATHERING_THRESHOLDS = REALM_THRESHOLDS[REALM_QI_GATHERING]
FOUNDATION_THRESHOLDS = REALM_THRESHOLDS[REALM_FOUNDATION]
GOLDEN_CORE_THRESHOLDS = REALM_THRESHOLDS[REALM_GOLDEN_CORE]
NASCENT_SOUL_THRESHOLDS = REALM_THRESHOLDS[REALM_NASCENT_SOUL]
SOUL_TRANSFORMATION_THRESHOLDS = REALM_THRESHOLDS[REALM_SOUL_TRANSFORMATION]
VOID_REFINING_THRESHOLDS = REALM_THRESHOLDS[REALM_VOID_REFINING]
DAO_UNION_THRESHOLDS = REALM_THRESHOLDS[REALM_DAO_UNION]
TRIBULATION_THRESHOLDS = REALM_THRESHOLDS[REALM_TRIBULATION]
FORMAL_REALMS = frozenset(REALM_THRESHOLDS)
BREATHING_STAMINA_COST = 2
BREATHING_DURATION_SECONDS = 10 * 60
BREATHING_BASE_CULTIVATION = 40
SPIRIT_SPRING_STAMINA_COST = 3
SPIRIT_SPRING_DURATION_SECONDS = 15 * 60
SPIRIT_SPRING_BASE_CULTIVATION = 70
SPIRIT_SPRING_ENVIRONMENT_BP = 11500
SPIRIT_SPRING_DAILY_LIMIT = 4
SECLUSION_STAMINA_COST = 6
SECLUSION_ENERGY_COST = 2
SECLUSION_DURATION_SECONDS = 30 * 60
SECLUSION_BASE_CULTIVATION = 170
SECLUSION_DAILY_LIMIT = 2
SOUL_REFINEMENT_STAMINA_COST = 8
SOUL_REFINEMENT_ENERGY_COST = 5
SOUL_REFINEMENT_DURATION_SECONDS = 30 * 60
SOUL_REFINEMENT_BASE_CULTIVATION = 5000
SOUL_REFINEMENT_SOUL_POWER_GAIN = 50
SOUL_REFINEMENT_SOUL_POWER_MAX = 300
SOUL_REFINEMENT_DAILY_LIMIT = 2
RECOVERY_PERIOD_SECONDS = 30 * 60
CULTIVATION_SETTLEMENT_GRACE_SECONDS = 24 * 60 * 60

SPIRIT_FIELD_LOCATION = "xuantian.spirit_field"
CULTIVATION_MODE_LABELS = {
    MODE_BREATHING: "调息修炼",
    MODE_SPIRIT_SPRING: "灵泉修炼",
    MODE_SECLUSION: "静修",
    MODE_SOUL_REFINEMENT: "神魂淬炼",
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
    if thresholds is None or layer < 0:
        return None
    next_layer = layer + 1
    if next_layer > REALM_MAX_LAYERS[realm_key]:
        return None
    minimum_layer = REALM_MAX_LAYERS[realm_key] - len(thresholds) + 1
    return thresholds[next_layer - minimum_layer]


def cultivation_mode(mode_key: str) -> CultivationMode:
    if mode_key == MODE_BREATHING:
        return CultivationMode(
            key=MODE_BREATHING,
            label=CULTIVATION_MODE_LABELS[MODE_BREATHING],
            stamina_cost=BREATHING_STAMINA_COST,
            energy_cost=0,
            duration_seconds=BREATHING_DURATION_SECONDS,
            base_cultivation=BREATHING_BASE_CULTIVATION,
            environment_bp=10000,
            daily_limit=None,
            required_realm=REALM_QI_SENSING,
            required_layer=1,
        )
    if mode_key == MODE_SPIRIT_SPRING:
        return CultivationMode(
            key=MODE_SPIRIT_SPRING,
            label=CULTIVATION_MODE_LABELS[MODE_SPIRIT_SPRING],
            stamina_cost=SPIRIT_SPRING_STAMINA_COST,
            energy_cost=0,
            duration_seconds=SPIRIT_SPRING_DURATION_SECONDS,
            base_cultivation=SPIRIT_SPRING_BASE_CULTIVATION,
            environment_bp=SPIRIT_SPRING_ENVIRONMENT_BP,
            daily_limit=SPIRIT_SPRING_DAILY_LIMIT,
            required_location=SPIRIT_FIELD_LOCATION,
            required_realm=REALM_QI_SENSING,
            required_layer=2,
        )
    if mode_key == MODE_SECLUSION:
        return CultivationMode(
            key=MODE_SECLUSION,
            label=CULTIVATION_MODE_LABELS[MODE_SECLUSION],
            stamina_cost=SECLUSION_STAMINA_COST,
            energy_cost=SECLUSION_ENERGY_COST,
            duration_seconds=SECLUSION_DURATION_SECONDS,
            base_cultivation=SECLUSION_BASE_CULTIVATION,
            environment_bp=10000,
            daily_limit=SECLUSION_DAILY_LIMIT,
            required_realm=REALM_QI_GATHERING,
            required_layer=1,
            requires_solitude=True,
        )
    if mode_key == MODE_SOUL_REFINEMENT:
        return CultivationMode(
            key=MODE_SOUL_REFINEMENT,
            label=CULTIVATION_MODE_LABELS[MODE_SOUL_REFINEMENT],
            stamina_cost=SOUL_REFINEMENT_STAMINA_COST,
            energy_cost=SOUL_REFINEMENT_ENERGY_COST,
            duration_seconds=SOUL_REFINEMENT_DURATION_SECONDS,
            base_cultivation=SOUL_REFINEMENT_BASE_CULTIVATION,
            environment_bp=10000,
            daily_limit=SOUL_REFINEMENT_DAILY_LIMIT,
            required_realm=REALM_NASCENT_SOUL,
            required_layer=1,
            requires_solitude=True,
            soul_power_gain=SOUL_REFINEMENT_SOUL_POWER_GAIN,
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
    manual_bonus_bp: int = 0,
) -> int:
    """Apply insight, environment, state and manual multipliers using integer bp."""

    insight = max(0, int(qualification.get("insight", 0)))
    environment = max(0, int(environment_bp))
    state = max(0, int(state_bp))
    manual = max(0, 10_000 + int(manual_bonus_bp))
    return (base * (200 + insight) * environment * state * manual) // (
        200 * 10_000 * 10_000 * 10_000
    )


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
