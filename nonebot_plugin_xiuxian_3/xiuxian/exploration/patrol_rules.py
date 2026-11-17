"""Strict repeatable patrol approaches and frozen narrative events."""

from __future__ import annotations

from copy import deepcopy

from ..content import ContentBundle, ContentError
from ..rewards.rules import reward_pool_map, reward_pool_outcomes
from ..utils.randomness import deterministic_weighted_choice


def patrol_definition(row: dict, bundle: ContentBundle) -> dict:
    value = row.get("patrol")
    if value is None and "patrol" not in row:
        return {}
    if not isinstance(value, dict) or set(value) != {"scene", "approaches", "events", "recipe_keys"}:
        raise ContentError("patrol requires scene, approaches, events and recipe_keys")
    if not isinstance(value["scene"], str) or len(value["scene"].strip()) < 30:
        raise ContentError("patrol scene is too short")
    approaches, events = value["approaches"], value["events"]
    if not isinstance(approaches, list) or not 2 <= len(approaches) <= 3:
        raise ContentError("patrol requires two or three approaches")
    names = set()
    for approach in approaches:
        if not isinstance(approach, dict) or set(approach) != {
            "key", "name", "desc", "duration_seconds", "stamina_cost", "energy_cost", "battle_chance_bp",
        }:
            raise ContentError("patrol approach has an invalid shape")
        for field in ("key", "name", "desc"):
            if not isinstance(approach[field], str) or not approach[field].strip():
                raise ContentError("patrol approach text is missing")
        for field in ("duration_seconds", "stamina_cost", "energy_cost", "battle_chance_bp"):
            if type(approach[field]) is not int or approach[field] < (1 if field == "duration_seconds" else 0):
                raise ContentError("patrol approach costs must be nonnegative integers")
        if approach["battle_chance_bp"] > 10000 or approach["key"] in names or approach["name"] in names:
            raise ContentError("patrol approach risk or alias is invalid")
        names.update((approach["key"], approach["name"]))
    if any(approaches[0][field] != row[field] for field in
           ("duration_seconds", "stamina_cost", "energy_cost", "battle_chance_bp")):
        raise ContentError("patrol default must match the exploration mode")
    if any(a["battle_chance_bp"] for a in approaches) and not row.get("enemy_pool_key"):
        raise ContentError("patrol encounter risk requires an enemy pool")
    if not isinstance(events, list) or len(events) < 3:
        raise ContentError("patrol requires at least three repeatable events")
    recipes = value["recipe_keys"]
    if not isinstance(recipes, list) or not recipes or any(not isinstance(key, str) for key in recipes) or len(set(recipes)) != len(recipes):
        raise ContentError("patrol requires unique recipe consumers")
    consumers = set()
    from ..production.rules import recipe_definition

    for key in recipes:
        try:
            consumers.update(recipe_definition(key, bundle).inputs)
        except ValueError as exc:
            raise ContentError("patrol recipe consumer is unavailable") from exc
    event_keys = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "key", "name", "weight", "start_text", "complete_text", "defeat_text", "expired_text", "pools",
        }:
            raise ContentError("patrol event has an invalid shape")
        for field in ("key", "name", "start_text", "complete_text", "defeat_text", "expired_text"):
            if not isinstance(event[field], str) or not event[field].strip():
                raise ContentError("patrol event text is missing")
        if event["key"] in event_keys or type(event["weight"]) is not int or event["weight"] <= 0:
            raise ContentError("patrol event weight or key is invalid")
        event_keys.add(event["key"])
        if not isinstance(event["pools"], dict) or set(event["pools"]) != {a["key"] for a in approaches}:
            raise ContentError("patrol event must cover every approach")
        for pool in event["pools"].values():
            for _, reward in reward_pool_outcomes(pool, bundle):
                if any(key.startswith("item.") and key not in consumers for key in reward):
                    raise ContentError("patrol material has no recipe consumer")
    return deepcopy(value)


def freeze_patrol(row: dict, bundle: ContentBundle, approach: str, seed: str) -> dict:
    patrol = patrol_definition(row, bundle)
    if not patrol:
        if approach:
            raise ValueError("this exploration has no patrol approaches")
        return {}
    selected = next((a for a in patrol["approaches"] if approach in {a["key"], a["name"]}), None) if approach else patrol["approaches"][0]
    if selected is None:
        raise ValueError("unknown patrol approach")
    event = deterministic_weighted_choice(tuple((e["weight"], e) for e in patrol["events"]), seed + ":patrol")
    pool = event["pools"][selected["key"]]
    return {
        "mode_label": row["name"], "scene": patrol["scene"], "approach": selected,
        "event": {key: event[key] for key in ("key", "name", "start_text", "complete_text", "defeat_text", "expired_text")},
        "candidates": [{"key": e["key"], "weight": e["weight"]} for e in patrol["events"]],
        "pool_key": pool, "reward": reward_pool_map(pool, seed=seed + ":patrol:reward", content=bundle),
        "uses": [{"name": bundle.label("recipe", key), "command": "生产预览 " + bundle.label("recipe", key)} for key in patrol["recipe_keys"]],
    }


def frozen_patrol(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"mode_label", "scene", "approach", "event", "candidates", "pool_key", "reward", "uses"}:
        raise ValueError("patrol snapshot has an invalid shape")
    for field in ("mode_label", "scene", "pool_key"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError("patrol snapshot text is missing")
    event, approach = value["event"], value["approach"]
    if not isinstance(event, dict) or set(event) != {"key", "name", "start_text", "complete_text", "defeat_text", "expired_text"} or any(not isinstance(v, str) or not v.strip() for v in event.values()):
        raise ValueError("patrol event snapshot is invalid")
    if not isinstance(approach, dict) or set(approach) != {"key", "name", "desc", "duration_seconds", "stamina_cost", "energy_cost", "battle_chance_bp"}:
        raise ValueError("patrol approach snapshot is invalid")
    if any(not isinstance(approach[k], str) or not approach[k].strip() for k in ("key", "name", "desc")) or any(type(approach[k]) is not int or approach[k] < 0 for k in ("duration_seconds", "stamina_cost", "energy_cost", "battle_chance_bp")) or not approach["duration_seconds"] or approach["battle_chance_bp"] > 10000:
        raise ValueError("patrol approach snapshot fields are invalid")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or not candidates or any(not isinstance(c, dict) or set(c) != {"key", "weight"} or not isinstance(c["key"], str) or type(c["weight"]) is not int or c["weight"] <= 0 for c in candidates) or len({c["key"] for c in candidates}) != len(candidates) or event["key"] not in {c["key"] for c in candidates}:
        raise ValueError("patrol candidate evidence is invalid")
    if not isinstance(value["reward"], dict) or not value["reward"] or any(not isinstance(k, str) or type(n) is not int or n <= 0 for k, n in value["reward"].items()):
        raise ValueError("patrol frozen reward is invalid")
    if not isinstance(value["uses"], list) or not value["uses"] or any(not isinstance(u, dict) or set(u) != {"name", "command"} or any(not isinstance(v, str) or not v.strip() for v in u.values()) for u in value["uses"]):
        raise ValueError("patrol uses are invalid")
    return deepcopy(value)
