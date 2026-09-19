"""Player repository port owned by the application boundary."""

from typing import Protocol

from ..domain.player import Player


class PlayerRepository(Protocol):
    def get_by_external_id(self, external_id: str) -> Player | None:
        """Find the single active or historical player for an external identity."""

    def get_by_platform_identity(self, platform: str, platform_user_id: str) -> Player | None:
        """Find the single player for a platform identity."""

    def add(self, player: Player) -> None:
        """Insert a player in the current transaction."""