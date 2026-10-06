"""Equipment-backed battle strength without invalid qualification fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

BALANCED_QUALIFICATION = dict.fromkeys(("body", "spirit", "insight", "root", "agility", "fortune"), 10)


def equip_damage_weapon(runtime, adapter: str, user: str, damage: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        weapon = connection.execute(
            "SELECT instance_id, affixes_json FROM equipment_instances WHERE player_id=? "
            "AND slot='weapon' AND equipped=1 AND status='active'", (player_id,)
        ).fetchone()
        if weapon is not None:
            affixes = {**json.loads(weapon[1]), "damage": damage}
            connection.execute(
                "UPDATE equipment_instances SET affixes_json=?, durability_bp=10000, updated_at=? "
                "WHERE instance_id=?", (json.dumps(affixes), now, weapon[0])
            )
            return
        connection.execute(
            "INSERT INTO equipment_instances(instance_id, player_id, item_key, label, slot, status, "
            "equipped, durability_bp, temper_level, max_temper_level, affixes_json, "
            "refinement_failure_streak, created_at, updated_at) "
            "VALUES (?, ?, 'item.weapon.wood_sword', '木纹剑', 'weapon', 'active', 1, 10000, 0, 3, ?, 0, ?, ?)",
            (f"battle-weapon:{uuid4().hex}", player_id, json.dumps({"damage": damage}), now, now),
        )
