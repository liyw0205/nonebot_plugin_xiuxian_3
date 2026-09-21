"""Framework-neutral Web adapter facade.

An HTTP framework can call ``dispatch`` after authenticating and normalizing
its request. Keeping this tiny facade dependency-free makes it usable from
FastAPI, Starlette, Flask, or a custom server without moving game rules here.
"""

from __future__ import annotations

from ..contracts import CommandContext, CommandResult
from ..runtime import XiuxianRuntime


async def dispatch(
    runtime: XiuxianRuntime,
    *,
    user_id: str,
    scene_id: str = "",
    nickname: str = "",
    command: str = "开始修仙",
) -> CommandResult:
    return await runtime.adapters.dispatch(
        "web",
        CommandContext(
            adapter="web",
            user_id=user_id,
            scene_id=scene_id,
            nickname=nickname,
        ),
        command,
    )
