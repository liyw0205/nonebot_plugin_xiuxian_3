"""Market-facing view of active temporary item bindings."""

from __future__ import annotations

import sqlite3


def active_binding_totals(
    connection: sqlite3.Connection, player_id: int, item_key: str, now_text: str,
) -> tuple[int, str | None]:
    row = connection.execute(
        """SELECT COALESCE(SUM(quantity), 0) AS quantity, MIN(bound_until) AS first_bound_until
        FROM (
            SELECT quantity, bound_until FROM item_bindings
            WHERE player_id=? AND item_key=? AND bound_until>?
            UNION ALL
            SELECT quantity, bound_until FROM season_item_bindings
            WHERE player_id=? AND item_key=? AND bound_until>?
            UNION ALL
            SELECT quantity, bound_until FROM exploration_item_bindings
            WHERE player_id=? AND item_key=? AND bound_until>?
        )""",
        (player_id, item_key, now_text) * 3,
    ).fetchone()
    return int(row["quantity"]), str(row["first_bound_until"]) if row["first_bound_until"] else None


__all__ = ["active_binding_totals"]
