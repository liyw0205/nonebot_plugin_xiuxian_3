"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from ..contracts import CommandContext, CommandResult
from .player.use_cases import PlayerApplication
from .production.use_cases import ProductionApplication
from .progression.use_cases import ProgressionApplication
from .progression.breakthrough.use_cases import BreakthroughApplication
from .world.use_cases import WorldApplication
from .exploration.use_cases import ExplorationApplication
from .repository import SQLitePlayerRepository


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.player = PlayerApplication(repository)
        self.progression = ProgressionApplication(repository)
        self.breakthrough = BreakthroughApplication(repository)
        self.production = ProductionApplication(repository)
        self.world = WorldApplication(repository)
        self.exploration = ExplorationApplication(repository)

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

    async def recover_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.progression.recover_cultivation(context)

    async def cancel_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.progression.cancel_cultivation(context)

    async def advance_layer(self, context: CommandContext) -> CommandResult:
        return await self.progression.advance_layer(context)

    async def recover_resources(self, context: CommandContext) -> CommandResult:
        return await self.progression.recover_resources(context)

    async def preview_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self.breakthrough.preview_breakthrough(context)

    async def start_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self.breakthrough.start_breakthrough(context)

    async def settle_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self.breakthrough.settle_breakthrough(context)

    async def recover_weakness(self, context: CommandContext) -> CommandResult:
        return await self.breakthrough.recover_weakness(context)

    async def preview_recipe(self, context: CommandContext) -> CommandResult:
        return await self.production.preview_recipe(context)

    async def start_production(self, context: CommandContext) -> CommandResult:
        return await self.production.start_production(context)

    async def complete_production(self, context: CommandContext) -> CommandResult:
        return await self.production.complete_production(context)

    async def recover_production(self, context: CommandContext) -> CommandResult:
        return await self.production.recover_production(context)

    async def preview_travel(self, context: CommandContext) -> CommandResult:
        return await self.world.preview_travel(context)

    async def start_travel(self, context: CommandContext) -> CommandResult:
        return await self.world.start_travel(context)

    async def start_cave_travel(self, context: CommandContext) -> CommandResult:
        return await self.world.start_travel(context, "cave.mist_grotto")

    async def settle_travel(self, context: CommandContext) -> CommandResult:
        return await self.world.settle_travel(context)

    async def start_exploration(self, context: CommandContext) -> CommandResult:
        return await self.exploration.start_exploration(context)

    async def settle_exploration(self, context: CommandContext) -> CommandResult:
        return await self.exploration.settle_exploration(context)

    async def cancel_exploration(self, context: CommandContext) -> CommandResult:
        return await self.exploration.cancel_exploration(context)
