"""Discovery-gated excavation supplies and receipt-bound restoration routes."""

from __future__ import annotations

from copy import deepcopy

from ..content import ContentError
from ..rewards.rules import reward_pool_outcomes


class RelicRequirementError(ValueError):
    pass


def _amounts(value):
    if not isinstance(value, dict) or not value or any(
        not isinstance(k, str) or not k.startswith("item.") or type(n) is not int or n <= 0
        for k, n in value.items()
    ):
        raise ContentError("relic assets require positive integer items")


def _metadata(value):
    if not isinstance(value, dict) or set(value) != {
        "survey_key", "supply_recipe_key", "costs", "cancel_seconds", "recipe_key", "commission_key",
        "scene", "complete_text", "defeat_text", "expired_text",
    }:
        raise ContentError("relic metadata fields are invalid")
    for key, text in value.items():
        if key not in {"costs", "cancel_seconds"} and (not isinstance(text, str) or not text.strip()):
            raise ContentError("relic text/reference is missing")
    if any(len(value[key]) < 30 for key in ("scene", "complete_text", "defeat_text", "expired_text")):
        raise ContentError("relic requires excavation and recovery narrative")
    if type(value["cancel_seconds"]) is not int or not 1 <= value["cancel_seconds"] <= 300:
        raise ContentError("relic cancellation window is invalid")
    _amounts(value["costs"])
    return value


def relic_definition(row, bundle):
    if "relic" not in row:
        return {}
    value = _metadata(row["relic"])
    if (row.get("patrol") or row.get("battle_chance_bp") != 10000 or not row.get("enemy_pool_key")
            or value["cancel_seconds"] >= row["duration_seconds"]):
        raise ContentError("relic must require combat and a preparation window")
    encounter = bundle.get("encounter_pool", row["enemy_pool_key"], include_locked=False)
    candidates = encounter.get("candidates") if encounter is not None else None
    if not isinstance(candidates, list) or not candidates:
        raise ContentError("relic requires a local encounter pool")
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("enemy_key"), str):
            raise ContentError("relic encounter candidate is malformed")
        enemy = bundle.get("enemy", candidate["enemy_key"], include_locked=False)
        if enemy is None or enemy.get("location_key") != row["location_key"]:
            raise ContentError("relic encounter must match the excavation location")
    site = bundle.get("survey", value["survey_key"], include_locked=False)
    if site is None or site.get("location_key") != row["location_key"]:
        raise ContentError("relic requires a local open survey")
    from ..production.rules import recipe_definition
    from ..livelihood.rules import town_commission_definitions

    try:
        supply = recipe_definition(value["supply_recipe_key"], bundle)
        restored = recipe_definition(value["recipe_key"], bundle)
        commission = town_commission_definitions(bundle)[value["commission_key"]]
    except (ValueError, KeyError) as exc:
        raise ContentError("relic production/delivery consumer is unavailable") from exc
    if any(supply.outputs.get(key, 0) < amount for key, amount in value["costs"].items()):
        raise ContentError("relic supply has no actual producer")
    if not any(bundle.require("item", key).get("equipment_slot") for key in restored.outputs):
        raise ContentError("relic restoration must produce usable equipment")
    delivered = set(commission.inputs)
    for _, reward in reward_pool_outcomes(row["reward_pool_key"], bundle):
        _amounts(reward)
        if set(reward) - set(restored.inputs) or set(reward) - delivered:
            raise ContentError("relic reward requires both restoration and delivery consumers")
    if bundle.require("reward", row["reward_pool_key"]).get("battle_failure_rewards"):
        raise ContentError("relic defeat cannot grant excavation rewards")
    return deepcopy(value)


def freeze_relic(row, bundle, discovery_operation_id, reward):
    definition = relic_definition(row, bundle)
    if not definition:
        return {}
    return frozen_relic({
        "definition": definition,
        "mode_key": row["key"], "mode_label": row["name"], "location_key": row["location_key"],
        "duration_seconds": row["duration_seconds"], "stamina_cost": row["stamina_cost"],
        "energy_cost": row["energy_cost"], "daily_limit": row["daily_limit"],
        "pool_key": row["reward_pool_key"], "reward": reward,
        "discovery_operation_id": discovery_operation_id,
        "uses": [
            {"name": bundle.label("recipe", definition["recipe_key"]),
             "command": "生产预览 " + bundle.label("recipe", definition["recipe_key"])},
            {"name": bundle.label("livelihood", definition["commission_key"]),
             "command": "接取委托 " + bundle.label("livelihood", definition["commission_key"])},
            {"name": bundle.label("recipe", definition["supply_recipe_key"]),
             "command": "生产预览 " + bundle.label("recipe", definition["supply_recipe_key"])},
        ],
    })


def frozen_relic(value):
    if not isinstance(value, dict) or set(value) != {
        "definition", "mode_key", "mode_label", "location_key", "duration_seconds", "stamina_cost",
        "energy_cost", "daily_limit", "pool_key", "reward", "discovery_operation_id", "uses",
    }:
        raise ContentError("relic snapshot fields are invalid")
    _metadata(value["definition"])
    for field in ("mode_key", "mode_label", "location_key", "pool_key", "discovery_operation_id"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ContentError("relic snapshot identity is invalid")
    for field in ("duration_seconds", "stamina_cost", "energy_cost", "daily_limit"):
        if type(value[field]) is not int or value[field] < (0 if field in {"stamina_cost", "energy_cost"} else 1):
            raise ContentError("relic snapshot cost/time is invalid")
    if value["definition"]["cancel_seconds"] >= value["duration_seconds"]:
        raise ContentError("relic snapshot preparation window is invalid")
    _amounts(value["reward"])
    if not isinstance(value["uses"], list) or len(value["uses"]) != 3:
        raise ContentError("relic snapshot uses are missing")
    for use in value["uses"]:
        if (not isinstance(use, dict) or set(use) != {"name", "command"}
                or any(not isinstance(text, str) or not text.strip() for text in use.values())):
            raise ContentError("relic snapshot use is invalid")
    return deepcopy(value)
