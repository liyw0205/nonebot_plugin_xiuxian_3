"""Immutable records exchanged by the v0.1 bounty application."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class BountyOfferView:
    key: str
    label: str
    description: str
    status: str
    progress: int
    target: int
    reward: dict[str, int]
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class BountyBoardRecord:
    player: PlayerView
    business_date: str
    offers: tuple[BountyOfferView, ...]


@dataclass(frozen=True, slots=True)
class BountyAcceptRecord:
    player: PlayerView
    bounty_key: str
    label: str
    status: str
    progress: int
    target: int
    starts_at: str
    expires_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BountyClaimRecord:
    player: PlayerView
    bounty_key: str
    label: str
    status: str
    progress: int
    target: int
    rewards: dict[str, int]
    already_completed: bool = False


__all__ = [
    "BountyAcceptRecord",
    "BountyBoardRecord",
    "BountyClaimRecord",
    "BountyOfferView",
]
