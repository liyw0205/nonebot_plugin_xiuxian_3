"""Composition root for lifecycle-safe runtime construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .adapters.base import AdapterRegistry, CommandRouter, register_core_commands
from .contracts import CommandContext, CommandResult
from .xiuxian.application import XiuxianApplication
from .xiuxian.content import ContentBundle
from .xiuxian.config import XiuxianSettings
from .xiuxian.repository import SQLitePlayerRepository


@dataclass(slots=True)
class XiuxianRuntime:
    settings: XiuxianSettings
    content: ContentBundle | None
    repository: SQLitePlayerRepository
    application: XiuxianApplication
    router: CommandRouter
    adapters: AdapterRegistry
    _closed: bool = False

    async def initialize(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
        await self.repository.initialize()

    async def dispatch(self, context: CommandContext, text: str) -> CommandResult:
        if self._closed:
            raise RuntimeError("runtime is closed")
        return await self.router.dispatch(context, text)

    async def close(self) -> None:
        self._closed = True


def create_runtime(
    *,
    settings: XiuxianSettings | None = None,
    data_dir: str | Path | None = None,
    adapters: tuple[str, ...] = ("onebot.v11", "qq.official", "nonebot", "web", "cli"),
    clock: Callable[[], datetime] | None = None,
) -> XiuxianRuntime:
    resolved_settings = settings or XiuxianSettings.from_env(data_dir)
    content = ContentBundle.load_optional(resolved_settings.data_dir)
    repository = SQLitePlayerRepository(resolved_settings, clock=clock)
    application = XiuxianApplication(repository)
    router = CommandRouter()
    register_core_commands(router, application)
    registry = AdapterRegistry.create(router)
    for adapter in adapters:
        registry.register(adapter)
    return XiuxianRuntime(
        settings=resolved_settings,
        content=content,
        repository=repository,
        application=application,
        router=router,
        adapters=registry,
    )
