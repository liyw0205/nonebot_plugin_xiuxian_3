from __future__ import annotations

import json


def mark_mainline_snapshot_legacy(runtime, adapter: str, user: str, stage_key: str) -> None:
    """Keep reward-focused tests on the pre-objective save format."""

    with runtime.repository._connect() as connection:
        row = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        run = connection.execute(
            "SELECT snapshot_json FROM mainline_runs WHERE player_id=? AND stage_key=?",
            (row["id"], stage_key),
        ).fetchone()
        snapshot = json.loads(run["snapshot_json"])
        snapshot.pop("started_at", None)
        definition = snapshot["definition"]
        for field in ("body", "objectives", "actions", "state_events", "next_stage_key", "retry_message"):
            definition.pop(field, None)
        connection.execute(
            "UPDATE mainline_runs SET snapshot_json=? WHERE player_id=? AND stage_key=?",
            (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), row["id"], stage_key),
        )


def grant_spirit_field_prerequisites(runtime, adapter: str, user: str, *, layer: int = 2) -> None:
    with runtime.repository._connect() as connection:
        row = connection.execute(
            "SELECT intro_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        intro = json.loads(row["intro_json"] or "{}")
        intro["flags"] = list(
            dict.fromkeys([*intro.get("flags", []), "guide.gather_blood_grass"])
        )
        connection.execute(
            "UPDATE players SET realm_key='qi_sensing', realm_layer=?, intro_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (layer, json.dumps(intro, ensure_ascii=False), adapter, user),
        )


def grant_blood_grass(runtime, adapter: str, user: str, quantity: int = 3) -> None:
    with runtime.repository._connect() as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        inventory = json.loads(row["inventory_json"] or "{}")
        inventory["item.herb.blood_grass"] = max(
            int(inventory.get("item.herb.blood_grass", 0)), quantity
        )
        connection.execute(
            "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), adapter, user),
        )
