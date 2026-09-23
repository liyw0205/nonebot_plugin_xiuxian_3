"""Versioned definitions for personal v0.6 endgame recipes."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b


CONTENT_VERSION = "content-0.6"
RULE_VERSION = "production-0.6.0"
SUCCESS_THRESHOLD_BP = 8_000
DAO_FRUIT_PROGRESS_CAP = 1_300
ASCENSION_CERTIFICATE_KEY = "item.ascension_certificate"


@dataclass(frozen=True, slots=True)
class EndgameRecipeDefinition:
    key: str
    duration_seconds: int
    inputs: dict[str, int]
    output_item: str | None = None
    output_progress: int = 0
    world_merit_cost: int = 0
    required_progress: int = 0
    required_ascension_merit: int = 0
    required_realm: str = "dao_union"


ENDGAME_RECIPES = {
    "recipe.dao.fruit_fragment": EndgameRecipeDefinition(
        key="recipe.dao.fruit_fragment",
        duration_seconds=20 * 60,
        inputs={"item.dao_fruit_fragment": 10, "item.soul_crystal": 5},
        output_progress=100,
        required_realm="dao_union",
    ),
    "recipe.tribulation.guard": EndgameRecipeDefinition(
        key="recipe.tribulation.guard",
        duration_seconds=30 * 60,
        inputs={"item.tribulation_token": 1, "item.domain_core": 3},
        output_item="item.tribulation_guard",
        required_realm="tribulation",
    ),
    "recipe.ascension.certificate": EndgameRecipeDefinition(
        key="recipe.ascension.certificate",
        duration_seconds=10 * 60,
        inputs={},
        output_item=ASCENSION_CERTIFICATE_KEY,
        world_merit_cost=1_000,
        required_progress=800,
        required_ascension_merit=1_000,
        required_realm="tribulation",
    ),
}

RECIPE_ALIASES = {
    **{key: key for key in ENDGAME_RECIPES},
    "道果碎片加工": "recipe.dao.fruit_fragment",
    "天劫保护阵": "recipe.tribulation.guard",
    "飞升凭证": "recipe.ascension.certificate",
}


def resolve_endgame_recipe(value: str) -> str | None:
    return RECIPE_ALIASES.get(value.strip())


def endgame_recipe(key: str) -> EndgameRecipeDefinition:
    return ENDGAME_RECIPES[key]


def recipe_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


__all__ = [
    "ASCENSION_CERTIFICATE_KEY",
    "CONTENT_VERSION",
    "DAO_FRUIT_PROGRESS_CAP",
    "ENDGAME_RECIPES",
    "EndgameRecipeDefinition",
    "RECIPE_ALIASES",
    "RULE_VERSION",
    "SUCCESS_THRESHOLD_BP",
    "endgame_recipe",
    "recipe_roll_bp",
    "resolve_endgame_recipe",
]
