"""Records returned by the demon-abyss application layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class DemonAbyssRunRecord:
    player: PlayerView
    run_id: str
    status: str
    node_index: int
    current_node: str | None
    allowed_nodes: tuple[str, ...]
    battle_id: str | None = None
    reward: dict[str, int] = field(default_factory=dict)
    first_clear: bool = False
    outcome: str | None = None
    expires_at: str = ""
    pollution_before: int = 0
    pollution_after: int = 0
    risk_roll_bp: int | None = None
    system_aborted: bool = False
    already_completed: bool = False


__all__ = ["DemonAbyssRunRecord"]
