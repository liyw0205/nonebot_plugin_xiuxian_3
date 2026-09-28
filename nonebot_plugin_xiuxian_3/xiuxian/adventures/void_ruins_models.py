"""Application records for void-ruins runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VoidRuinsRunRecord:
    run_id: str
    party_id: str
    status: str
    node_index: int
    current_node: str | None
    battle_id: str | None
    expires_at: str
    rewards: dict[str, dict[str, int]] = field(default_factory=dict)
    first_clear_members: tuple[str, ...] = ()
    outcome: str | None = None
    already_completed: bool = False


__all__ = ["VoidRuinsRunRecord"]
