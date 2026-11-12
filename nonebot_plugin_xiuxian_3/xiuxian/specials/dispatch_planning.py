"""Optional fieldwork preparations and immutable narrative receipts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from ..content import ContentBundle, ContentError


def _text(value: Any, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{subject} must be non-empty text")
    return value


def _fields(value: Any, fields: set[str], subject: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContentError(f"{subject} requires exactly {sorted(fields)}")
    return value


def planning_definition(row: dict, bundle: ContentBundle) -> dict | None:
    if "planning" not in row:
        return None
    from .dispatch_rules import _parse_dispatch
    from ..production.rules import recipe_definitions
    from ..livelihood.rules import town_commission_definitions
    from ..exploration.rules import _definitions
    from ..rewards.rules import reward_pool_outcomes

    subject = f"dispatch {row['key']} planning"
    result = deepcopy(_fields(row["planning"], {"npc", "scene", "sources", "recipe_keys", "commission_keys", "plans"}, subject))
    for field in ("npc", "scene"):
        _text(result[field], subject)
    if not row.get("requirements", {}).get("location_key"):
        raise ContentError(f"{subject} requires a worksite location")
    plans = result["plans"]
    if not isinstance(plans, list) or len(plans) < 2:
        raise ContentError(f"{subject} requires at least two preparations")
    selectors: set[str] = set()
    inputs: set[str] = set()
    outputs: set[str] = set()
    for index, plan in enumerate(plans):
        _fields(plan, {"key", "name", "desc", "duration_seconds", "cost", "risk", "rewards", "failure_refunds", "start_text", "outcome_texts"}, subject)
        key = _text(plan["key"], subject)
        if not key.isascii() or not key.replace("_", "").isalnum():
            raise ContentError(f"{subject} invalid preparation key {key!r}")
        name = _text(plan["name"], subject)
        for selector in (key, name):
            if selector in selectors:
                raise ContentError(f"{subject} duplicate preparation selector {selector!r}")
            selectors.add(selector)
        for field in ("desc", "start_text"):
            _text(plan[field], subject)
        _fields(plan["outcome_texts"], {"success", "delayed", "partial", "failed"}, subject)
        for text in plan["outcome_texts"].values():
            _text(text, subject)
        candidate = {k: v for k, v in row.items() if k != "planning"}
        for field in ("duration_seconds", "cost", "risk", "rewards", "failure_refunds"):
            candidate[field] = plan[field]
            if index == 0 and row.get(field) != plan[field]:
                raise ContentError(f"{subject} default preparation differs from {field}")
        definition = _parse_dispatch(candidate, bundle)
        inputs.update(key for key, _ in definition.costs if key.startswith("item."))
        outputs.update(key for _, rewards in definition.rewards for key in dict(rewards) if key.startswith("item."))
    sources = result["sources"]
    if not isinstance(sources, list) or not sources:
        raise ContentError(f"{subject} requires public material sources")
    explorations = _definitions(bundle)
    source_items: set[str] = set()
    for source in sources:
        _fields(source, {"item_key", "exploration_key"}, subject)
        item = _text(source["item_key"], subject)
        mode_key = _text(source["exploration_key"], subject)
        mode = bundle.get("exploration_mode", mode_key, include_locked=False)
        if mode_key not in explorations or mode is None or not any(
            rewards.get(item, 0) > 0 for _, rewards in reward_pool_outcomes(mode["reward_pool_key"], bundle)
        ):
            raise ContentError(f"{subject} {mode_key!r} does not produce {item!r}")
        if item in source_items:
            raise ContentError(f"{subject} duplicate material source {item!r}")
        source_items.add(item)
    if inputs != source_items:
        raise ContentError(f"{subject} material sources must match preparation costs")
    consumed: set[str] = set()
    for field, definitions in (("recipe_keys", recipe_definitions(bundle)), ("commission_keys", town_commission_definitions(bundle))):
        keys = result[field]
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
            raise ContentError(f"{subject} invalid {field}")
        for key in keys:
            if key not in definitions or not set(definitions[key].inputs) & outputs:
                raise ContentError(f"{subject} {key!r} must consume fieldwork output")
            consumed.update(set(definitions[key].inputs) & outputs)
    if consumed != outputs:
        raise ContentError(f"{subject} every output requires a real consumer")
    return result


def select_preparation(definition, value: str | None, bundle: ContentBundle):
    if definition.planning is None:
        if value:
            raise ValueError(f"{definition.label}没有筹备方案：{value}")
        return definition
    plans = definition.planning["plans"]
    plan = next((p for p in plans if value in (p["key"], p["name"])), None) if value else plans[0]
    if plan is None:
        raise ValueError(f"{definition.label}没有筹备方案：{value}")
    from .dispatch_rules import _parse_costs, _parse_refunds, _parse_rewards

    costs = _parse_costs(plan["cost"], definition.key, bundle)
    return replace(definition, duration_seconds=plan["duration_seconds"], costs=tuple(costs.items()),
                   risk_weights=tuple(plan["risk"]["weights"].items()),
                   rewards=tuple(_parse_rewards(plan["rewards"], definition.key, bundle).items()),
                   failure_refunds=tuple(_parse_refunds(plan["failure_refunds"], definition.key, costs).items()),
                   preparation=deepcopy(plan))


def freeze_planning(definition, outcome: str, bundle: ContentBundle) -> dict | None:
    if definition.planning is None or definition.preparation is None:
        return None
    plan = definition.preparation
    planning = definition.planning
    keys = {key for key, _ in definition.costs} | {key for _, rewards in definition.rewards for key in dict(rewards)}
    def label(key):
        if key in {"stamina", "energy", "spirit_stones", "service_reputation"}:
            return {"stamina": "体力", "energy": "精力", "spirit_stones": "灵石", "service_reputation": "服务信誉"}[key]
        kind = "item" if key.startswith("item.") else "codex_entry" if key.startswith("codex.") else "location"
        return bundle.label(kind, key.removeprefix("local."))
    return {
        "plan_key": plan["key"], "plan_name": plan["name"], "plan_desc": plan["desc"],
        "npc": planning["npc"], "scene": planning["scene"], "start_text": plan["start_text"],
        "result_text": plan["outcome_texts"][outcome],
        "asset_labels": {key: label(key) for key in keys},
        "uses": [{"name": bundle.label("recipe" if field == "recipe_keys" else "livelihood", key),
                  "command": f"生产预览 {key}" if field == "recipe_keys" else f"接取委托 {key}"}
                 for field in ("recipe_keys", "commission_keys") for key in planning[field]],
    }


def validate_frozen_planning(value: Any) -> dict:
    result = _fields(value, {"plan_key", "plan_name", "plan_desc", "npc", "scene", "start_text", "result_text", "asset_labels", "uses"}, "dispatch planning snapshot")
    for field in ("plan_key", "plan_name", "plan_desc", "npc", "scene", "start_text", "result_text"):
        _text(result[field], f"dispatch planning {field}")
    labels = result["asset_labels"]
    if not isinstance(labels, dict) or not labels:
        raise ContentError("dispatch planning requires frozen asset labels")
    for key, label in labels.items():
        _text(key, "dispatch asset key")
        _text(label, "dispatch asset label")
    if not isinstance(result["uses"], list) or not result["uses"]:
        raise ContentError("dispatch planning requires frozen consumers")
    for use in result["uses"]:
        _fields(use, {"name", "command"}, "dispatch planning use")
        _text(use["name"], "dispatch use name")
        _text(use["command"], "dispatch use command")
    return result
