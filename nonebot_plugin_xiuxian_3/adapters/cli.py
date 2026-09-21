"""CLI adapter facade for diagnostics and local administration."""

from __future__ import annotations

from ..contracts import CommandContext, CommandResult
from ..runtime import XiuxianRuntime


async def dispatch(
    runtime: XiuxianRuntime,
    *,
    user_id: str,
    scene_id: str = "cli",
    nickname: str = "",
    command: str = "开始修仙",
) -> CommandResult:
    return await runtime.adapters.dispatch(
        "cli",
        CommandContext(
            adapter="cli",
            user_id=user_id,
            scene_id=scene_id,
            nickname=nickname,
        ),
        command,
    )
