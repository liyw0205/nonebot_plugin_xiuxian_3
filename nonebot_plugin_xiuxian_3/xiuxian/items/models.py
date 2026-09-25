"""Records exchanged by item use application services."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ItemUseRecord:
    player: PlayerView
    item_key: str
    item_name: str
    quantity: int
    effect: dict[str, object]
    already_completed: bool = False


__all__ = ["ItemUseRecord"]
