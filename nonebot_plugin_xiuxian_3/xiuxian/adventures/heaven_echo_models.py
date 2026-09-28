"""Application records for heaven-echo runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HeavenEchoRunRecord:
    run_id: str
    status: str
    node_index: int
    current_node: str | None
    expires_at: str
    outcome: str | None = None
    first_clear: bool = False
    story_flag_written: bool = False
    already_completed: bool = False


__all__ = ["HeavenEchoRunRecord"]
