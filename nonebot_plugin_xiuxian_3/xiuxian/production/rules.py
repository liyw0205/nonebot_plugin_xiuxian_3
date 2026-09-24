"""Pure rules for the v0.1 personal production slice."""

from __future__ import annotations

from hashlib import blake2b

from .endgame_work_rules import (
    ENDGAME_WORK_RECIPES,
    ITEM_LABELS as ENDGAME_WORK_ITEM_LABELS,
    RECIPE_ALIASES as ENDGAME_WORK_RECIPE_ALIASES,
)
from .recipe_models import RecipeDefinition


RECIPE_RULE_VERSION = "production-0.1.0"
QUALITY_SUCCESS_THRESHOLD_BP = 4500
HIGH_QUALITY_THRESHOLD_BP = 8000
TOOL_MAX_DURABILITY_BP = 2000


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
    "recipe.array.mist_barrier": RecipeDefinition(
        key="recipe.array.mist_barrier",
        name="迷雾屏障阵",
        profession="formation",
        inputs={"item.mat.array_sand": 5, "item.herb.spirit_leaf": 2},
        energy_cost=12,
        duration_seconds=240,
        daily_limit=2,
        tool_key=None,
        tool_cost_bp=0,
        currency_cost=100,
        outputs={"item.array.mist_barrier": 1},
        high_quality_bonus={},
        failure_refunds={"item.mat.array_sand": 3, "item.herb.spirit_leaf": 1},
        min_realm_layer=1,
        required_realm="golden_core",
        proficiency_bp=4000,
        required_location=("xuantian.array_hall", "cave.mist_grotto_2"),
        content_version="content-0.2",
        rule_version="production-0.2.0",
        success_threshold_bp=6000,
        high_quality_threshold_bp=8000,
    ),
}
RECIPES.update(ENDGAME_WORK_RECIPES)


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
    "迷雾屏障阵": "recipe.array.mist_barrier",
    "迷雾屏障": "recipe.array.mist_barrier",
}
RECIPE_ALIASES.update({key: key for key in ENDGAME_WORK_RECIPES})
RECIPE_ALIASES.update(ENDGAME_WORK_RECIPE_ALIASES)

ITEM_LABELS = {
    "item.herb.blood_grass": "止血草",
    "item.herb.spirit_leaf": "灵叶",
    "item.food.coarse_spirit_rice": "粗糙灵米",
    "item.ore.ironstone": "铁石",
    "item.mat.wood": "木材",
    "item.mat.array_sand": "阵砂",
    "item.pill.healing_low": "低阶疗伤丹",
    "item.weapon.wood_sword": "木纹剑",
    "item.array.gathering_basic": "基础聚灵阵",
    "item.array.mist_barrier": "迷雾屏障阵",
    "item.tool.basic_furnace": "基础丹炉",
    "item.tool.basic_hammer": "基础炼器锤",
}
ITEM_LABELS.update(ENDGAME_WORK_ITEM_LABELS)


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
