"""Pure rules for the v0.1 personal production slice."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b


RECIPE_RULE_VERSION = "production-0.1.0"
QUALITY_SUCCESS_THRESHOLD_BP = 4500
HIGH_QUALITY_THRESHOLD_BP = 8000
TOOL_MAX_DURABILITY_BP = 2000


@dataclass(frozen=True, slots=True)
class RecipeDefinition:
    key: str
    name: str
    profession: str
    inputs: dict[str, int]
    energy_cost: int
    duration_seconds: int
    daily_limit: int
    tool_key: str | None
    tool_cost_bp: int
    currency_cost: int
    outputs: dict[str, int]
    high_quality_bonus: dict[str, int]
    failure_refunds: dict[str, int]
    min_realm_layer: int
    required_realm: str
    required_location: tuple[str, ...] = ()
    teaching_allowed: bool = False


RECIPES: dict[str, RecipeDefinition] = {
    "recipe.pill.healing_low": RecipeDefinition(
        key="recipe.pill.healing_low",
        name="低阶疗伤丹",
        profession="alchemy",
        inputs={"item.herb.blood_grass": 2, "item.food.coarse_spirit_rice": 1},
        energy_cost=4,
        duration_seconds=30,
        daily_limit=8,
        tool_key="item.tool.basic_furnace",
        tool_cost_bp=100,
        currency_cost=0,
        outputs={"item.pill.healing_low": 1},
        high_quality_bonus={"item.pill.healing_low": 1},
        failure_refunds={"item.herb.blood_grass": 1, "item.food.coarse_spirit_rice": 0},
        min_realm_layer=1,
        required_realm="qi_sensing",
        teaching_allowed=True,
    ),
    "recipe.weapon.wood_sword": RecipeDefinition(
        key="recipe.weapon.wood_sword",
        name="木纹剑",
        profession="artifice",
        inputs={"item.ore.ironstone": 2, "item.mat.wood": 2},
        energy_cost=5,
        duration_seconds=60,
        daily_limit=4,
        tool_key="item.tool.basic_hammer",
        tool_cost_bp=100,
        currency_cost=0,
        outputs={"item.weapon.wood_sword": 1},
        high_quality_bonus={},
        failure_refunds={"item.ore.ironstone": 1, "item.mat.wood": 1},
        min_realm_layer=1,
        required_realm="qi_gathering",
    ),
    "recipe.array.gathering_basic": RecipeDefinition(
        key="recipe.array.gathering_basic",
        name="基础聚灵阵",
        profession="formation",
        inputs={"item.mat.array_sand": 2},
        energy_cost=6,
        duration_seconds=90,
        daily_limit=3,
        tool_key=None,
        tool_cost_bp=0,
        currency_cost=20,
        outputs={"item.array.gathering_basic": 1},
        high_quality_bonus={},
        failure_refunds={"item.mat.array_sand": 1},
        min_realm_layer=1,
        required_realm="qi_gathering",
        required_location=("xuantian.spirit_field", "xuantian.array_hall"),
    ),
}


RECIPE_ALIASES = {
    **{key: key for key in RECIPES},
    "疗伤丹": "recipe.pill.healing_low",
    "低阶疗伤丹": "recipe.pill.healing_low",
    "炼丹": "recipe.pill.healing_low",
    "木纹剑": "recipe.weapon.wood_sword",
    "木剑": "recipe.weapon.wood_sword",
    "炼器": "recipe.weapon.wood_sword",
    "聚灵阵": "recipe.array.gathering_basic",
    "基础聚灵阵": "recipe.array.gathering_basic",
    "布阵": "recipe.array.gathering_basic",
}

ITEM_LABELS = {
    "item.herb.blood_grass": "止血草",
    "item.food.coarse_spirit_rice": "粗糙灵米",
    "item.ore.ironstone": "铁石",
    "item.mat.wood": "木材",
    "item.mat.array_sand": "阵砂",
    "item.pill.healing_low": "低阶疗伤丹",
    "item.weapon.wood_sword": "木纹剑",
    "item.array.gathering_basic": "基础聚灵阵",
    "item.tool.basic_furnace": "基础丹炉",
    "item.tool.basic_hammer": "基础炼器锤",
}


def resolve_recipe(value: str) -> str | None:
    return RECIPE_ALIASES.get(value.strip())


def recipe_definition(recipe_key: str) -> RecipeDefinition:
    try:
        return RECIPES[recipe_key]
    except KeyError as exc:
        raise ValueError(f"unsupported production recipe: {recipe_key}") from exc


def item_label(item_key: str) -> str:
    return ITEM_LABELS.get(item_key, "生产物资")


def random_quality_bp(operation_id: str) -> int:
    """Derive the weighted quality roll from the stable operation identity."""

    value = blake2b(operation_id.encode("utf-8"), digest_size=1).digest()[0]
    if value < 128:
        return 0
    if value < 217:
        return 500
    return 1000


def production_quality(
    *,
    material_quality_bp: int,
    proficiency_bp: int,
    tool_durability_bp: int,
    random_quality_bp_value: int,
) -> int:
    value = (
        (max(0, material_quality_bp) * 4000) // 10000
        + (max(0, proficiency_bp) * 3000) // 10000
        + (max(0, tool_durability_bp) * 2000) // 10000
        + max(0, random_quality_bp_value)
    )
    return min(10000, value)


__all__ = [
    "HIGH_QUALITY_THRESHOLD_BP",
    "QUALITY_SUCCESS_THRESHOLD_BP",
    "RECIPE_RULE_VERSION",
    "TOOL_MAX_DURABILITY_BP",
    "RecipeDefinition",
    "production_quality",
    "random_quality_bp",
    "item_label",
    "recipe_definition",
    "resolve_recipe",
]
