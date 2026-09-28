"""Application records for dao-origin runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DaoOriginRunRecord:
    run_id: str
    status: str
    node_index: int
    current_node: str | None
    expires_at: str
    outcome: str | None = None
    first_clear: bool = False
    story_flag_written: bool = False
    codex_written: bool = False
    already_completed: bool = False


__all__ = ["DaoOriginRunRecord"]
