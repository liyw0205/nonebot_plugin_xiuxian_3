"""Definitions for personal endgame recipes (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b

from .content_rules import endgame_defaults, endgame_records

_ENDGAME_DEFAULTS = endgame_defaults()

SUCCESS_THRESHOLD_BP = int(_ENDGAME_DEFAULTS["success_threshold_bp"])
DAO_FRUIT_PROGRESS_CAP = int(_ENDGAME_DEFAULTS["dao_fruit_progress_cap"])
ASCENSION_CERTIFICATE_KEY = str(_ENDGAME_DEFAULTS["ascension_certificate_key"])


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
    required_endgame_statuses: tuple[str, ...] = ()
    required_location: str = "dao.origin_gate"


def _definition(record: dict) -> EndgameRecipeDefinition:
    return EndgameRecipeDefinition(
        key=str(record["key"]),
        duration_seconds=int(record["duration_seconds"]),
        inputs=dict(record["inputs"]),
        output_item=record.get("output_item"),
        output_progress=int(record.get("output_progress", 0)),
        world_merit_cost=int(record.get("world_merit_cost", 0)),
        required_progress=int(record.get("required_progress", 0)),
        required_ascension_merit=int(record.get("required_ascension_merit", 0)),
        required_realm=str(record["required_realm"]),
        required_endgame_statuses=tuple(record.get("required_endgame_statuses", ())),
        required_location=str(record.get("required_location", "dao.origin_gate")),
    )


ENDGAME_RECIPES = {
    str(record["key"]): _definition(record) for record in endgame_records()
}

RECIPE_ALIASES = {
    **{str(record["key"]): str(record["key"]) for record in endgame_records()},
    **{
        alias: str(record["key"])
        for record in endgame_records()
        for alias in record["aliases"]
    },
}


def resolve_endgame_recipe(value: str) -> str | None:
    return RECIPE_ALIASES.get(value.strip())


def endgame_recipe(key: str) -> EndgameRecipeDefinition:
    return ENDGAME_RECIPES[key]


def recipe_roll_bp(operation_id: str) -> int:
    return int.from_bytes(blake2b(operation_id.encode("utf-8"), digest_size=2).digest(), "big") % 10_000


__all__ = [
    "ASCENSION_CERTIFICATE_KEY",
    "DAO_FRUIT_PROGRESS_CAP",
    "ENDGAME_RECIPES",
    "EndgameRecipeDefinition",
    "RECIPE_ALIASES",
    "SUCCESS_THRESHOLD_BP",
    "endgame_recipe",
    "recipe_roll_bp",
    "resolve_endgame_recipe",
]
