"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from ..contracts import CommandContext, CommandResult
from .player.use_cases import PlayerApplication
from .repository import SQLitePlayerRepository


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.player = PlayerApplication(repository)

    async def create_player(self, context: CommandContext) -> CommandResult:
        return await self.player.create_player(context)

    async def start_seeking(self, context: CommandContext) -> CommandResult:
        return await self.player.start_seeking(context)

    async def get_profile(self, context: CommandContext) -> CommandResult:
        return await self.player.get_profile(context)

    async def rename_player(self, context: CommandContext) -> CommandResult:
        return await self.player.rename_player(context)
