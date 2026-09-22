"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from ..contracts import CommandContext, CommandResult
from .player.use_cases import PlayerApplication
from .progression.use_cases import ProgressionApplication
from .repository import SQLitePlayerRepository


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.player = PlayerApplication(repository)
        self.progression = ProgressionApplication(repository)

    async def create_player(self, context: CommandContext) -> CommandResult:
        return await self.player.create_player(context)

    async def start_seeking(self, context: CommandContext) -> CommandResult:
        return await self.player.start_seeking(context)

    async def get_profile(self, context: CommandContext) -> CommandResult:
        return await self.player.get_profile(context)

    async def rename_player(self, context: CommandContext) -> CommandResult:
        return await self.player.rename_player(context)

    async def complete_intro(self, context: CommandContext) -> CommandResult:
        return await self.player.complete_intro(context)

    async def travel_intro(self, context: CommandContext, destination: str) -> CommandResult:
        return await self.player.travel_intro(context, destination)

    async def enter_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.player.enter_cultivation(context)

    async def start_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.progression.start_cultivation(context)

    async def settle_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.progression.settle_cultivation(context)

    async def cancel_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.progression.cancel_cultivation(context)

    async def advance_layer(self, context: CommandContext) -> CommandResult:
        return await self.progression.advance_layer(context)

    async def recover_resources(self, context: CommandContext) -> CommandResult:
        return await self.progression.recover_resources(context)
