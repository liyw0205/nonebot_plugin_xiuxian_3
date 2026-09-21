"""Shared command routing contracts for every transport."""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import replace

from ..contracts import CommandContext, CommandResult
from ..xiuxian.application import XiuxianApplication

Handler = Callable[[CommandContext], Awaitable[CommandResult]]


class EventDeduplicator:
    """Bounded in-process event deduplication for adapter retries."""

    def __init__(self, *, ttl_seconds: float = 600.0, max_entries: int = 16_384):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("deduplicator limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def accept(self, key: str) -> bool:
        """Return false when the same non-empty key was accepted recently."""

        if not key:
            return True
        now = time.monotonic()
        with self._lock:
            expired = [item for item, deadline in self._seen.items() if deadline <= now]
            for item in expired:
                self._seen.pop(item, None)
            if key in self._seen:
                return False
            self._seen[key] = now + self.ttl_seconds
            if len(self._seen) > self.max_entries:
                oldest = min(self._seen, key=self._seen.get)
                self._seen.pop(oldest, None)
            return True


class CommandRouter:
    """Lock-free read path after startup registration is complete."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, command: str, handler: Handler, *, aliases: tuple[str, ...] = ()) -> None:
        names = (command, *aliases)
        for name in names:
            normalized = name.strip().lower()
            if not normalized:
                raise ValueError("command cannot be empty")
            if normalized in self._handlers:
                raise ValueError(f"command already registered: {name}")
            self._handlers[normalized] = handler

    async def dispatch(self, context: CommandContext, text: str) -> CommandResult:
        parts = text.strip().split() if text.strip() else []
        command = parts[0].lower() if parts else ""
        handler = self._handlers.get(command)
        if handler is None:
            return CommandResult(
                ok=False,
                code="COMMAND_NOT_FOUND",
                message="暂未找到这个指令。",
                request_id=context.request_id,
            )
        if parts[1:]:
            context = replace(context, command_args=tuple(parts[1:]))
        return await handler(context)

    @property
    def commands(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


@dataclass(slots=True)
class AdapterRegistry:
    """Maps adapter names to one shared router without adapter-specific rules."""

    router: CommandRouter
    _adapters: set[str]

    @classmethod
    def create(cls, router: CommandRouter) -> "AdapterRegistry":
        return cls(router=router, _adapters=set())

    def register(self, name: str) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("adapter name cannot be empty")
        self._adapters.add(normalized)

    async def dispatch(self, adapter: str, context: CommandContext, text: str) -> CommandResult:
        normalized = adapter.strip().lower()
        if normalized not in self._adapters:
            return CommandResult(
                ok=False,
                code="ADAPTER_NOT_REGISTERED",
                message="当前适配器尚未启用。",
                request_id=context.request_id,
            )
        return await self.router.dispatch(context, text)


def register_core_commands(router: CommandRouter, application: XiuxianApplication) -> None:
    router.register("开始修仙", application.create_player)
    router.register("寻仙问道", application.start_seeking)
    router.register("我的状态", application.get_profile, aliases=("我的修仙信息",))
    router.register("修仙改名", application.rename_player, aliases=("改名",))
