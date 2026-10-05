"""Pure rules for the first cultivation loop."""

from __future__ import annotations


from collections.abc import Mapping
from typing import Any

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
            description="可查看闭关修炼的开放条件；聚气后才可执行。",
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
            description="可查看下一境界的突破准备，但感气九层尚不能闭关突破。",
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
            description="已达到感气混元，可检查聚气突破所需的材料、地点和状态。",
        ),
    ),
}


def formal_realms(content: ContentBundle | None = None) -> frozenset[str]:
    """Return active realms from the runtime content bundle."""

    if content is None:
        return frozenset(REALM_THRESHOLDS)
    thresholds, _ = _content_thresholds(content)
    return frozenset(thresholds)


def next_layer_threshold(
    realm_key: str,
    layer: int,
    content: ContentBundle | None = None,
) -> int | None:
    if content is None:
        thresholds_map, max_layers = REALM_THRESHOLDS, REALM_MAX_LAYERS
    else:
        thresholds_map, max_layers = _content_thresholds(content)
    thresholds = thresholds_map.get(realm_key)
    if thresholds is None or layer < 0:
        return None
    next_layer = layer + 1
    if next_layer > max_layers[realm_key]:
        return None
    minimum_layer = max_layers[realm_key] - len(thresholds) + 1
    return thresholds[next_layer - minimum_layer]


def _positive_int(row: Mapping[str, Any], key: str, mode_key: str, *, zero: bool = False) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or (value < 0 if zero else value <= 0):
        bound = "non-negative" if zero else "positive"
        raise ContentError(f"cultivation {mode_key} {key} must be a {bound} integer")
    return value


def cultivation_definitions(content: ContentBundle | None = None) -> dict[str, CultivationMode]:
    bundle = content or bundled_content()
    definitions: dict[str, CultivationMode] = {}
    references: dict[str, str] = {}
    for row in bundle.list("cultivation", include_locked=False):
        mode_key = row.get("key")
        if not isinstance(mode_key, str) or not mode_key.startswith("cultivate."):
            raise ContentError(f"cultivation record has invalid key: {mode_key!r}")
        if mode_key in definitions:
            raise ContentError(f"duplicate cultivation key: {mode_key}")
        name = row.get("name")
        desc = row.get("desc")
        if not isinstance(name, str) or not name.strip() or not isinstance(desc, str) or not desc.strip():
            raise ContentError(f"cultivation {mode_key} requires name and desc")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"cultivation {mode_key} aliases must be a string list")
        aliases = [alias.strip() for alias in aliases]
        for reference in (mode_key, name.strip(), *aliases):
            if reference in references:
                raise ContentError(f"duplicate cultivation name or alias: {reference}")
            references[reference] = mode_key
        required_realm = row.get("required_realm")
        if not isinstance(required_realm, str) or not bundle.has("realm", required_realm, include_locked=False):
            raise ContentError(f"cultivation {mode_key} references an unknown required realm")
        required_layer = _positive_int(row, "required_layer", mode_key, zero=True)
        max_layer = bundle.require("realm", required_realm, include_locked=False).get("layer_max")
        if not isinstance(max_layer, int) or required_layer < 1 or required_layer > max_layer:
            raise ContentError(f"cultivation {mode_key} required_layer is outside {required_realm}")
        location = row.get("required_location")
        if location is not None and (not isinstance(location, str) or not bundle.has("location", location, include_locked=False)):
            raise ContentError(f"cultivation {mode_key} references an unknown location")
        daily_limit = row.get("daily_limit")
        if daily_limit is not None:
            daily_limit = _positive_int(row, "daily_limit", mode_key)
        requires_solitude = row.get("requires_solitude")
        if not isinstance(requires_solitude, bool):
            raise ContentError(f"cultivation {mode_key} requires_solitude must be boolean")
        soul_power_max = _positive_int(row, "soul_power_max", mode_key, zero=True)
        soul_power_gain = _positive_int(row, "soul_power_gain", mode_key, zero=True)
        if soul_power_gain and not soul_power_max:
            raise ContentError(f"cultivation {mode_key} needs a positive soul_power_max")
        if soul_power_gain > soul_power_max:
            raise ContentError(f"cultivation {mode_key} soul_power_gain exceeds soul_power_max")
        definitions[mode_key] = CultivationMode(
            key=mode_key,
            label=name.strip(),
            stamina_cost=_positive_int(row, "stamina_cost", mode_key),
            energy_cost=_positive_int(row, "energy_cost", mode_key, zero=True),
            duration_seconds=_positive_int(row, "duration_seconds", mode_key),
            base_cultivation=_positive_int(row, "base_cultivation", mode_key),
            environment_bp=_positive_int(row, "environment_bp", mode_key),
            daily_limit=daily_limit,
            aliases=tuple(aliases),
            required_location=location,
            required_realm=required_realm,
            required_layer=required_layer,
            requires_solitude=requires_solitude,
            soul_power_gain=soul_power_gain,
            soul_power_max=soul_power_max,
        )
    return definitions


def cultivation_mode(mode_key: str, content: ContentBundle | None = None) -> CultivationMode:
    try:
        return cultivation_definitions(content)[mode_key]
    except KeyError as exc:
        raise ValueError(f"unsupported cultivation mode: {mode_key}") from exc


def resolve_cultivation_mode(value: str, content: ContentBundle | None = None) -> str:
    normalized = (value or "").strip()
    definitions = cultivation_definitions(content)
    matches = [key for key, definition in definitions.items() if normalized == key or normalized == definition.label or normalized in definition.aliases]
    if len(matches) != 1:
        raise ValueError(f"unknown or ambiguous cultivation mode: {value}")
    return matches[0]


def cultivation_mode_label(mode_key: str, content: ContentBundle | None = None) -> str:
    return cultivation_mode(mode_key, content).label


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


def can_advance_layer(
    realm_key: str,
    layer: int,
    cultivation: int,
    content: ContentBundle | None = None,
) -> bool:
    threshold = next_layer_threshold(realm_key, layer, content)
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
