"""Composition root for lifecycle-safe runtime construction."""

from __future__ import annotations

import asyncio
import logging
import os
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

_LOGGER = logging.getLogger(__name__)
_DISPATCH_RECOVERY_INTERVAL_SECONDS = 60


def _bundled_content_dirs() -> tuple[Path, ...]:
    """Return package and source-tree content locations in priority order."""

    package_data = Path(__file__).resolve().parent / "data"
    source_data = Path(__file__).resolve().parents[1] / "data"
    return (package_data, source_data)


def _load_content(settings: XiuxianSettings, *, explicit_data_dir: str | Path | None, explicit_settings: bool) -> ContentBundle | None:
    content = ContentBundle.load_optional(settings.data_dir)
    if content is not None or explicit_data_dir is not None or explicit_settings:
        return content
    # A wheel contains the read-only content pack.  Keep the default database
    # under the host project's ./data while using the bundled pack as a source.
    if os.getenv("XIUXIAN3_DATA_DIR"):
        return content
    for candidate in _bundled_content_dirs():
        content = ContentBundle.load_optional(candidate)
        if content is not None:
            return content
    return None


@dataclass(slots=True)
class XiuxianRuntime:
    settings: XiuxianSettings
    content: ContentBundle | None
    repository: SQLitePlayerRepository
    application: XiuxianApplication
    router: CommandRouter
    adapters: AdapterRegistry
    _closed: bool = False
    _dispatch_recovery_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
        await self.repository.initialize()
        if self._dispatch_recovery_task is None:
            self._dispatch_recovery_task = asyncio.create_task(
                self._dispatch_recovery_loop(), name="xiuxian3-dispatch-recovery"
            )

    async def _dispatch_recovery_loop(self) -> None:
        while not self._closed:
            try:
                await self.repository.recover_expired_dispatches()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("dispatch recovery pass failed")
            await asyncio.sleep(_DISPATCH_RECOVERY_INTERVAL_SECONDS)

    async def dispatch(self, context: CommandContext, text: str) -> CommandResult:
        if self._closed:
            raise RuntimeError("runtime is closed")
        return await self.router.dispatch(context, text)

    async def close(self) -> None:
        self._closed = True
        task = self._dispatch_recovery_task
        self._dispatch_recovery_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_runtime(
    *,
    settings: XiuxianSettings | None = None,
    data_dir: str | Path | None = None,
    adapters: tuple[str, ...] = ("onebot.v11", "qq.official", "nonebot", "web", "cli"),
    clock: Callable[[], datetime] | None = None,
) -> XiuxianRuntime:
    resolved_settings = settings or XiuxianSettings.from_env(data_dir)
    content = _load_content(
        resolved_settings,
        explicit_data_dir=data_dir,
        explicit_settings=settings is not None,
    )
    repository = SQLitePlayerRepository(resolved_settings, clock=clock)
    application = XiuxianApplication(repository, content)
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
