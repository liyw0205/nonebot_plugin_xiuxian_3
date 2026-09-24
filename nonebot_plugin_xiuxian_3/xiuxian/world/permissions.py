"""Shared permission checks for world facilities used by other domains."""

from __future__ import annotations

import json
from typing import Any

from .cloud_rules import ARRAY_HALL_INVITE_FLAG


def array_hall_permission(connection: Any, player: Any) -> str | None:
    """Return the granted array-hall permission, or ``None`` when absent.

    Production and the explicit world-entry command must agree on this check;
    keeping the SQL and invitation flag handling here prevents a production
    recipe from bypassing the facility gate.
    """

    membership = connection.execute(
        "SELECT 1 FROM sect_members WHERE player_id = ? AND status = 'active' LIMIT 1",
        (player["id"],),
    ).fetchone()
    if membership is not None:
        return "sect_member"
    try:
        intro = json.loads(str(player["intro_json"] or "{}"))
    except (TypeError, ValueError):
        intro = {}
    flags = {str(item) for item in intro.get("flags", [])} if isinstance(intro, dict) else set()
    if {ARRAY_HALL_INVITE_FLAG, "array_hall_invite"} & flags:
        return "teaching_invite"
    return None


__all__ = ["array_hall_permission"]
