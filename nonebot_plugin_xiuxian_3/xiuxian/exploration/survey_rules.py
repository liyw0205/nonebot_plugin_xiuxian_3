"""Strict field investigation content and immutable in-progress snapshots."""

from __future__ import annotations

from copy import deepcopy

from ..content import ContentBundle, ContentError


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"survey {label} must be nonempty text")


def _amounts(value, *, resources=False):
    if not isinstance(value, dict) or not value:
        raise ContentError("survey amounts must be a nonempty object")
    for key, amount in value.items():
        if (not isinstance(key, str) or not (key.startswith("item.") or resources and key in {"stamina", "energy"})
                or type(amount) is not int or amount <= 0):
            raise ContentError("survey amounts require positive integer items/resources")


def validate_survey(value):
    fields = {"key", "name", "desc", "status", "location_key", "required_realm", "required_layer",
              "prerequisite", "nodes", "rewards", "recipe_keys", "completion_text", "uses"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ContentError("survey fields are invalid")
    for field in ("key", "name", "desc", "location_key", "required_realm", "completion_text"):
        _text(value[field], field)
    if len(value["desc"]) < 30 or len(value["completion_text"]) < 20:
        raise ContentError("survey requires field narrative and completion text")
    if value["status"] not in {"active", "open", "locked"}:
        raise ContentError("survey status is invalid")
    if type(value["required_layer"]) is not int or value["required_layer"] < 1:
        raise ContentError("survey realm layer is invalid")
    if value["prerequisite"] is not None:
        _text(value["prerequisite"], "prerequisite")
    _amounts(value["rewards"])
    recipes, uses = value["recipe_keys"], value["uses"]
    if (not isinstance(recipes, list) or not recipes or any(not isinstance(k, str) or not k for k in recipes)
            or len(set(recipes)) != len(recipes) or not isinstance(uses, list) or len(uses) != len(recipes)):
        raise ContentError("survey recipe consumers are invalid")
    for use in uses:
        if not isinstance(use, dict) or set(use) != {"name", "command"}:
            raise ContentError("survey use fields are invalid")
        for text in use.values():
            _text(text, "use")
    nodes = value["nodes"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 6:
        raise ContentError("survey requires two to six field nodes")
    node_keys, choice_selectors = set(), set()
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"key", "name", "body", "choices"}:
            raise ContentError("survey node fields are invalid")
        for field in ("key", "name", "body"):
            _text(node[field], "node " + field)
        if len(node["body"]) < 20 or node["key"] in node_keys:
            raise ContentError("survey node narrative/key is invalid")
        node_keys.add(node["key"])
        if not isinstance(node["choices"], list) or not 2 <= len(node["choices"]) <= 3:
            raise ContentError("survey node requires two or three choices")
        for choice in node["choices"]:
            if not isinstance(choice, dict) or set(choice) != {
                "key", "name", "desc", "costs", "success_bp", "seconds", "success_text", "failure_text",
            }:
                raise ContentError("survey choice fields are invalid")
            for field in ("key", "name", "desc", "success_text", "failure_text"):
                _text(choice[field], "choice " + field)
            if choice["key"] == choice["name"] or {choice["key"], choice["name"]} & choice_selectors:
                raise ContentError("survey choice selectors must be unique")
            choice_selectors.update((choice["key"], choice["name"]))
            _amounts(choice["costs"], resources=True)
            if (type(choice["success_bp"]) is not int or not 1 <= choice["success_bp"] <= 10000
                    or type(choice["seconds"]) is not int or not 1 <= choice["seconds"] <= 3600):
                raise ContentError("survey choice chance/time is invalid")
        if not any(c["success_bp"] == 10000 for c in node["choices"]):
            raise ContentError("survey must offer a reliable observation choice")
    return deepcopy(value)


def survey_definitions(bundle: ContentBundle):
    from ..production.rules import recipe_definitions

    rows = bundle.list("survey")
    available_recipes = recipe_definitions(bundle) if rows else {}
    result, selectors = {}, set()
    for row in rows:
        if "uses" in row:
            raise ContentError("survey uses are derived from actual recipes")
        recipes = row.get("recipe_keys")
        if not isinstance(recipes, list) or any(not isinstance(k, str) for k in recipes):
            raise ContentError("survey recipe keys are invalid")
        uses, consumers = [], set()
        for key in recipes:
            try:
                recipe = available_recipes[key]
            except (ValueError, KeyError) as exc:
                raise ContentError("survey recipe is unavailable") from exc
            consumers.update(recipe.inputs)
            uses.append({"name": bundle.label("recipe", key), "command": "生产预览 " + bundle.label("recipe", key)})
        value = validate_survey({**row, "uses": uses})
        for kind, key in (("location", value["location_key"]), ("realm", value["required_realm"])):
            if not bundle.has(kind, key, include_locked=False):
                raise ContentError(f"survey references unavailable {kind}:{key}")
        if value["required_layer"] > bundle.require("realm", value["required_realm"])["layer_max"]:
            raise ContentError("survey layer exceeds realm layers")
        if set(value["rewards"]) - consumers:
            raise ContentError("survey reward lacks an actual recipe consumer")
        for amounts in [value["rewards"], *(c["costs"] for n in value["nodes"] for c in n["choices"])]:
            for key in amounts:
                if key.startswith("item.") and not bundle.has("item", key, include_locked=False):
                    raise ContentError("survey item is unavailable")
        if value["key"] == value["name"] or {value["key"], value["name"]} & selectors:
            raise ContentError("survey selectors must be unique")
        selectors.update((value["key"], value["name"]))
        result[value["key"]] = value
    for value in result.values():
        seen = {value["key"]}
        parent = value["prerequisite"]
        while parent:
            if (parent in seen or parent not in result or value["status"] in {"active", "open"}
                    and result[parent]["status"] not in {"active", "open"}):
                raise ContentError("survey prerequisite is unavailable or cyclic")
            seen.add(parent)
            parent = result[parent]["prerequisite"]
    return result


def resolve_survey(bundle, selector):
    for value in survey_definitions(bundle).values():
        if selector in {value["key"], value["name"]} and value["status"] in {"active", "open"}:
            return value
    raise LookupError("未找到开放勘察点，请查看山野手札。")
