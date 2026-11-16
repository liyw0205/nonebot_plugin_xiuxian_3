"""Story objectives proved by a newly planted, fully maintained harvest."""

from __future__ import annotations

import sqlite3

from ..content import ContentBundle, ContentError
from ..utils.json_cache import decode_json_strict


def field_harvest_objective(value: dict, bundle: ContentBundle | None = None) -> dict:
    fields = {"key", "type", "label", "crop_key", "plan_keys", "item_key", "quantity"}
    plans = value.get("plan_keys")
    if (
        set(value) != fields or value.get("type") != "field_harvest"
        or any(not isinstance(value.get(key), str) or not value[key].strip()
               for key in ("key", "label", "crop_key", "item_key"))
        or type(value.get("quantity")) is not int or value["quantity"] <= 0
        or not isinstance(plans, list) or not plans
        or any(not isinstance(plan, str) or not plan.strip() for plan in plans)
        or len(set(plans)) != len(plans)
    ):
        raise ContentError("mainline field_harvest has an invalid shape")
    if bundle is not None:
        from ..livelihood.rules import crop_definitions

        crop = crop_definitions(bundle).get(value["crop_key"])
        if crop is None or not crop.cultivation:
            raise ContentError("mainline field_harvest references an unknown cultivated crop")
        definitions = {plan["key"]: plan for plan in crop.cultivation["plans"]}
        for key in plans:
            plan = definitions.get(key)
            if plan is None or any(
                event["harvest"].get(value["item_key"], 0) < value["quantity"]
                for event in plan["events"]
            ):
                raise ContentError("mainline field_harvest is not guaranteed by its crop plan")
    return {**value, "plan_keys": list(plans)}


def has_field_harvest(
    connection: sqlite3.Connection, player_id: int, objective: dict, baseline: int,
) -> bool:
    from ..livelihood.cultivation_rules import validate_frozen_cultivation

    # Plant-operation order excludes an old plot harvested after the stage,
    # including plots planted in the same clock tick as the stage start.
    plots = connection.execute(
        "SELECT f.*, p.rowid AS plant_rowid FROM field_plots f JOIN operations p "
        "ON p.operation_id=f.operation_id AND p.player_id=f.player_id "
        "WHERE f.player_id=? AND f.crop_key=? AND f.status='harvested' "
        "AND p.operation_name='livelihood.plant' AND p.rowid>?",
        (player_id, objective["crop_key"], baseline),
    ).fetchall()
    for plot in plots:
        snapshot = decode_json_strict(plot["snapshot_json"])
        result = decode_json_strict(plot["result_json"])
        if not isinstance(snapshot, dict) or not isinstance(result, dict):
            raise ValueError("mainline field evidence is invalid")
        if "cultivation" not in snapshot:
            continue
        cultivation = validate_frozen_cultivation(snapshot["cultivation"])
        required = snapshot.get("required_maintenance")
        if (
            snapshot.get("crop_key") != plot["crop_key"]
            or type(required) is not int or required <= 0
            or not 0 <= plot["maintenance_count"] <= required
            or type(result.get("maintained")) is not bool
            or result["maintained"] != (plot["maintenance_count"] >= required)
        ):
            raise ValueError("mainline field evidence disagrees with its snapshot")
        expected = cultivation["event"]["harvest" if result["maintained"] else "unmaintained_harvest"]
        if result.get("harvest") != expected or any(type(n) is not int for n in result["harvest"].values()):
            raise ValueError("mainline field reward disagrees with its snapshot")
        if not result["maintained"] or cultivation["plan_key"] not in objective["plan_keys"]:
            continue
        operations = connection.execute(
            "SELECT result_json FROM operations WHERE player_id=? "
            "AND operation_name='livelihood.harvest' AND rowid>? ORDER BY rowid",
            (player_id, plot["plant_rowid"]),
        ).fetchall()
        for operation in operations:
            payload = decode_json_strict(operation["result_json"])
            if not isinstance(payload, dict):
                raise ValueError("mainline field harvest operation is invalid")
            if payload.get("plot_id") != plot["plot_id"]:
                continue
            if (
                payload.get("crop_key") != plot["crop_key"] or payload.get("status") != "harvested"
                or payload.get("harvest") != expected or payload.get("cultivation") != cultivation
                or type(payload.get("maintenance_count")) is not int
                or payload["maintenance_count"] != plot["maintenance_count"]
                or type(payload.get("required_maintenance")) is not int
                or payload["required_maintenance"] != required
                or any(type(n) is not int for n in payload["harvest"].values())
            ):
                raise ValueError("mainline field harvest operation disagrees with its plot")
            if expected.get(objective["item_key"], 0) >= objective["quantity"]:
                return True
    return False
