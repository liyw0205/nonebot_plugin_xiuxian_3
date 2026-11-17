"""Renewable, finite player-owned resource veins and real upkeep supplies."""

from __future__ import annotations

from copy import deepcopy

from ..content import ContentError
from .survey_rules import _amounts, _text, survey_definitions


def validate_deposit(value):
    if not isinstance(value, dict) or set(value) != {
        "key", "name", "desc", "status", "survey_key", "capacity", "regen_seconds", "regen_units",
        "plans", "maintenance", "recipe_keys", "uses",
    }:
        raise ContentError("deposit fields are invalid")
    for field in ("key", "name", "desc", "survey_key"):
        _text(value[field], "deposit " + field)
    if len(value["desc"]) < 30 or value["status"] not in {"active", "open", "locked"}:
        raise ContentError("deposit description/status is invalid")
    for field in ("capacity", "regen_seconds", "regen_units"):
        if type(value[field]) is not int or not 1 <= value[field] <= 100000:
            raise ContentError("deposit capacity/regeneration is invalid")
    if value["regen_units"] > value["capacity"]:
        raise ContentError("deposit regeneration exceeds capacity")
    plans = value["plans"]
    if not isinstance(plans, list) or not 2 <= len(plans) <= 3:
        raise ContentError("deposit requires two or three extraction plans")
    selectors = set()
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {
            "key", "name", "desc", "costs", "stock_cost", "recovery_delay", "cooldown_seconds", "rewards", "text",
        }:
            raise ContentError("deposit extraction plan fields are invalid")
        for field in ("key", "name", "desc", "text"):
            _text(plan[field], "deposit plan " + field)
        if plan["key"] == plan["name"] or {plan["key"], plan["name"]} & selectors:
            raise ContentError("deposit plan selectors are not unique")
        selectors.update((plan["key"], plan["name"]))
        _amounts(plan["costs"], resources=True)
        _amounts(plan["rewards"])
        for field in ("stock_cost", "cooldown_seconds", "recovery_delay"):
            if type(plan[field]) is not int or not (0 if field == "recovery_delay" else 1) <= plan[field] <= 100000:
                raise ContentError("deposit plan costs/recovery are invalid")
        if plan["stock_cost"] > value["capacity"]:
            raise ContentError("deposit extraction exceeds capacity")
    maintenance = value["maintenance"]
    if not isinstance(maintenance, dict) or set(maintenance) != {
        "costs", "restore_units", "daily_limit", "cooldown_seconds", "recipe_key", "text",
    }:
        raise ContentError("deposit maintenance fields are invalid")
    _amounts(maintenance["costs"], resources=True)
    for field in ("recipe_key", "text"):
        _text(maintenance[field], "deposit maintenance " + field)
    for field in ("restore_units", "daily_limit", "cooldown_seconds"):
        if type(maintenance[field]) is not int or not 1 <= maintenance[field] <= 100000:
            raise ContentError("deposit maintenance quantities are invalid")
    if maintenance["restore_units"] > value["capacity"]:
        raise ContentError("deposit maintenance exceeds capacity")
    recipes, uses = value["recipe_keys"], value["uses"]
    if (not isinstance(recipes, list) or not recipes or any(not isinstance(k, str) or not k for k in recipes)
            or len(set(recipes)) != len(recipes) or not isinstance(uses, list) or len(uses) != len(recipes)):
        raise ContentError("deposit recipe consumers are invalid")
    for use in uses:
        if not isinstance(use, dict) or set(use) != {"name", "command"}:
            raise ContentError("deposit consumer links are invalid")
        for text in use.values():
            _text(text, "deposit consumer")
    return deepcopy(value)


def deposit_definitions(bundle):
    from ..production.rules import recipe_definitions

    rows = bundle.list("deposit")
    if not rows:
        return {}
    recipes, surveys = recipe_definitions(bundle), survey_definitions(bundle)
    result, selectors = {}, set()
    for row in rows:
        if "uses" in row or not isinstance(row.get("recipe_keys"), list):
            raise ContentError("deposit consumer links must come from recipes")
        consumers, uses = set(), []
        for key in row["recipe_keys"]:
            if not isinstance(key, str) or key not in recipes:
                raise ContentError("deposit recipe consumer is unavailable")
            consumers.update(recipes[key].inputs)
            uses.append({"name": bundle.label("recipe", key), "command": "生产预览 " + bundle.label("recipe", key)})
        value = validate_deposit({**row, "uses": uses})
        parent = surveys.get(value["survey_key"])
        if parent is None or value["status"] in {"active", "open"} and parent["status"] not in {"active", "open"}:
            raise ContentError("deposit requires an available field survey")
        if value["key"] == value["name"] or {value["key"], value["name"]} & selectors:
            raise ContentError("deposit selectors are not unique")
        selectors.update((value["key"], value["name"]))
        maintenance = value["maintenance"]
        recipe = recipes.get(maintenance["recipe_key"])
        supplies = {k: n for k, n in maintenance["costs"].items() if k.startswith("item.")}
        if not recipe or not supplies or any(recipe.outputs.get(k, 0) < n for k, n in supplies.items()):
            raise ContentError("deposit upkeep supplies lack an actual recipe source")
        for plan in value["plans"]:
            if set(plan["rewards"]) - consumers:
                raise ContentError("deposit resource lacks a real production consumer")
            for amounts in (plan["costs"], plan["rewards"]):
                for key in amounts:
                    if key.startswith("item.") and not bundle.has("item", key, include_locked=False):
                        raise ContentError("deposit item is unavailable")
        result[value["key"]] = value
    renewable = {key for value in result.values() if value["status"] in {"active", "open"}
                 for plan in value["plans"] for key in plan["rewards"]}
    for value in result.values():
        if value["status"] in {"active", "open"} and set(recipes[value["maintenance"]["recipe_key"]].inputs) - renewable:
            raise ContentError("deposit upkeep recipe inputs lack renewable deposit sources")
    return result
