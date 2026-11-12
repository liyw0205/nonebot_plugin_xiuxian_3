"""Optional crop plans, public seed chains and frozen field events."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..content import ContentBundle, ContentError
from ..utils.randomness import deterministic_weighted_choice


def _text(value: Any, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{subject} must be non-empty text")
    return value


def _positive(value: Any, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{subject} must be a positive integer")
    return value


def _fields(value: Any, fields: set[str], subject: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContentError(f"{subject} requires exactly {sorted(fields)}")
    return value


def cultivation_definition(row: dict, bundle: ContentBundle) -> dict | None:
    if "cultivation" not in row:
        return None
    subject = f"livelihood {row['key']} cultivation"
    result = deepcopy(_fields(row["cultivation"], {"seed_source", "recipe_keys", "commission_keys", "plans"}, subject))
    plans = result["plans"]
    if not isinstance(plans, list) or not plans:
        raise ContentError(f"{subject} requires plans")
    selectors: set[str] = set()
    all_harvests: list[dict] = []
    for plan in plans:
        _fields(plan, {"key", "name", "desc", "growth_seconds", "plant_energy", "maintenance_energy", "required_maintenance", "harvest_window_seconds", "events"}, subject)
        key = _text(plan["key"], subject)
        if not key.isascii() or not key.replace("_", "").isalnum():
            raise ContentError(f"{subject} invalid plan key {key!r}")
        name = _text(plan["name"], subject)
        _text(plan["desc"], subject)
        for selector in (key, name):
            if selector in selectors:
                raise ContentError(f"{subject} duplicate plan selector {selector!r}")
            selectors.add(selector)
        for field in ("growth_seconds", "plant_energy", "maintenance_energy", "required_maintenance", "harvest_window_seconds"):
            _positive(plan[field], f"{subject} {key} {field}")
        events = plan["events"]
        if not isinstance(events, list) or not events:
            raise ContentError(f"{subject} {key} requires events")
        event_keys = set()
        for event in events:
            _fields(event, {"key", "name", "weight", "start_text", "maintenance_text", "complete_text", "fallback_text", "harvest", "unmaintained_harvest"}, subject)
            event_key = _text(event["key"], subject)
            if not event_key.isascii() or not event_key.replace("_", "").isalnum() or event_key in event_keys:
                raise ContentError(f"{subject} invalid or duplicate event key {event_key!r}")
            event_keys.add(event_key)
            _positive(event["weight"], subject)
            for field in ("name", "start_text", "maintenance_text", "complete_text", "fallback_text"):
                _text(event[field], f"{subject} {key} {event_key} {field}")
            for field in ("harvest", "unmaintained_harvest"):
                harvest = event[field]
                if not isinstance(harvest, dict) or not harvest:
                    raise ContentError(f"{subject} {field} requires item rewards")
                for item, quantity in harvest.items():
                    if not bundle.has("item", item, include_locked=False):
                        raise ContentError(f"{subject} unknown harvest item {item!r}")
                    _positive(quantity, f"{subject} {item}")
                all_harvests.append(harvest)
    from ..production.rules import recipe_definitions
    from .rules import town_commission_definitions

    recipes = recipe_definitions(bundle)
    commissions = town_commission_definitions(bundle)
    for field, definitions in (("recipe_keys", recipes), ("commission_keys", commissions)):
        keys = result[field]
        if not isinstance(keys, list) or (field == "recipe_keys" and not keys) or any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
            raise ContentError(f"{subject} invalid {field}")
        for key in keys:
            if key not in definitions or not any(set(definitions[key].inputs) & set(harvest) for harvest in all_harvests):
                raise ContentError(f"{subject} {key!r} must consume a harvest item")
    source = result["seed_source"]
    if not isinstance(source, dict):
        raise ContentError(f"{subject} requires seed_source")
    expected = {"kind", "key", "command"} | ({"plan_key"} if source.get("kind") == "crop_plan" else set())
    _fields(source, expected, subject)
    _text(source["command"], subject)
    seed = row["seed"]["item_key"]
    if source["kind"] == "guide":
        producer = bundle.get("guide", source["key"], include_locked=False)
        if producer is None or producer.get("output", {}).get("item_key") != seed:
            raise ContentError(f"{subject} guide does not produce seed {seed}")
    elif source["kind"] == "exploration":
        from ..exploration.rules import _definitions
        from ..rewards.rules import reward_pool_outcomes
        producer = _definitions(bundle).get(source["key"])
        pool = bundle.get("exploration_mode", source["key"], include_locked=False)
        if producer is None or not any(rewards.get(seed, 0) > 0 for _, rewards in reward_pool_outcomes(pool["reward_pool_key"], bundle)):
            raise ContentError(f"{subject} exploration does not produce seed {seed}")
    elif source["kind"] == "crop_plan":
        producer = bundle.get("livelihood", source["key"], include_locked=False)
        candidates = producer.get("cultivation", {}).get("plans", []) if producer else []
        plan = next((plan for plan in candidates if plan["key"] == source["plan_key"]), None)
        if source["key"] == row["key"] or plan is None or not all(event["harvest"].get(seed, 0) > 0 for event in plan["events"]):
            raise ContentError(f"{subject} crop plan does not produce seed {seed}")
    else:
        raise ContentError(f"{subject} unsupported seed source")
    return result


def resolve_plan(cultivation: dict | None, value: str) -> dict:
    if cultivation:
        for plan in cultivation["plans"]:
            if value in (plan["key"], plan["name"]):
                return plan
    raise ValueError(f"没有照料方案：{value}")


def freeze_cultivation(cultivation: dict, plan: dict, operation_id: str, bundle: ContentBundle) -> dict:
    seed = f"livelihood.cultivation:{operation_id}:{plan['key']}"
    event = deterministic_weighted_choice(((event["weight"], event) for event in plan["events"]), seed)
    return {
        "plan_key": plan["key"], "plan_name": plan["name"], "random_seed": seed,
        "event": deepcopy(event), "harvest_window_seconds": plan["harvest_window_seconds"],
        "uses": [
            {"name": bundle.label("recipe" if field == "recipe_keys" else "livelihood", key),
             "command": f"生产预览 {key}" if field == "recipe_keys" else f"接取委托 {key}"}
            for field in ("recipe_keys", "commission_keys") for key in cultivation[field]
        ],
    }


def validate_frozen_cultivation(value: Any) -> dict:
    result = _fields(value, {"plan_key", "plan_name", "random_seed", "event", "harvest_window_seconds", "uses"}, "field cultivation snapshot")
    for field in ("plan_key", "plan_name", "random_seed"):
        _text(result[field], f"field cultivation {field}")
    _positive(result["harvest_window_seconds"], "field cultivation window")
    event = _fields(result["event"], {"key", "name", "weight", "start_text", "maintenance_text", "complete_text", "fallback_text", "harvest", "unmaintained_harvest"}, "field event")
    for field in ("key", "name", "start_text", "maintenance_text", "complete_text", "fallback_text"):
        _text(event[field], f"field event {field}")
    _positive(event["weight"], "field event weight")
    for field in ("harvest", "unmaintained_harvest"):
        harvest = event[field]
        if not isinstance(harvest, dict) or not harvest:
            raise ContentError(f"field event {field} must contain items")
        for key, quantity in harvest.items():
            if not isinstance(key, str) or not key.startswith("item."):
                raise ContentError("field event must reward items only")
            _positive(quantity, f"field event {key}")
    if not isinstance(result["uses"], list) or not result["uses"]:
        raise ContentError("field cultivation requires frozen uses")
    for use in result["uses"]:
        _fields(use, {"name", "command"}, "field cultivation use")
        _text(use["name"], "field use name")
        _text(use["command"], "field use command")
    return result
