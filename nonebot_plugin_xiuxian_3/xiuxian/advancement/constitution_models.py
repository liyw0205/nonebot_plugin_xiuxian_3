"""Application records for constitution selection and reshaping."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ConstitutionRecord:
    player: PlayerView
    constitution_key: str
    label: str
    description: str
    effect: dict[str, int | str] = field(default_factory=dict)
    status: str = "selected"
    selected_at: str = ""
    last_reshaped_at: str | None = None
    reshape_count: int = 0
    already_completed: bool = False


__all__ = ["ConstitutionRecord"]
