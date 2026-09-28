"""Application records for ancestral-hall runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AncestralHallRunRecord:
    run_id: str
    status: str
    node_index: int
    current_node: str | None
    battle_id: str | None = None
    outcome: str | None = None
    expires_at: str = ""
    first_clear: bool = False
    already_completed: bool = False
    story_flag_written: bool = False


__all__ = ["AncestralHallRunRecord"]
