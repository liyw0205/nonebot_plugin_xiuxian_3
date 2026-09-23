"""Records returned by the personal endgame recipe workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class EndgameRecipeRecord:
    player: PlayerView
    session_id: str
    recipe_key: str
    status: str
    starts_at: str
    ends_at: str
    success: bool | None = None
    roll_bp: int | None = None
    rewards: dict[str, int] = field(default_factory=dict)
    refunds: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["EndgameRecipeRecord"]
