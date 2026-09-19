"""Text and button command adapter for the registration/info slice."""

from __future__ import annotations

from ..application.player import (
    GetPlayerInfo,
    GetPlayerInfoQuery,
    RegisterPlayer,
    RegisterPlayerCommand,
)
from ..domain.player import Player
from ..adapters.contracts import CommandContext, ReplyPlan


class PlayerCommandAdapter:
    REGISTER_COMMANDS = frozenset({"我要修仙", "重入仙途"})
    INFO_COMMANDS = frozenset({"我的修仙信息", "我的状态", "我的 id", "我的ID"})

    def __init__(self, register: RegisterPlayer, info: GetPlayerInfo) -> None:
        self._register = register
        self._info = info

    def handle(self, context: CommandContext) -> ReplyPlan:
        command = " ".join(context.text.split())
        if context.actor_id is None or not context.can_write_assets:
            return ReplyPlan("无法确认你的身份或会话场景，当前请求不会改变资产。")
        if command in self.REGISTER_COMMANDS:
            result = self._register.execute(
                RegisterPlayerCommand(
                    actor_id=context.actor_id,
                    operation_id=f"message:{context.message_id}",
                )
            )
            if not result.ok:
                return ReplyPlan(result.error.message)
            return ReplyPlan(self._registration_text(result.value))
        if command in self.INFO_COMMANDS or command.casefold() in {"我的id", "我的 id"}:
            result = self._info.execute(GetPlayerInfoQuery(actor_id=context.actor_id))
            if not result.ok:
                return ReplyPlan(result.error.message)
            return ReplyPlan(self._info_text(result.value))
        return ReplyPlan("暂未识别该命令。")

    def handle_button(self, context: CommandContext) -> ReplyPlan:
        return self.handle(context)

    @staticmethod
    def _registration_text(player: Player) -> str:
        return f"修仙角色创建成功：{player.player_id}，境界：{player.realm}。"

    @staticmethod
    def _info_text(player: Player) -> str:
        return (
            f"角色：{player.nickname}（{player.external_id}）\n"
            f"境界：{player.realm}\n"
            f"等级：{player.level}\n"
            f"修为：{player.cultivation}\n"
            f"灵石：{player.spirit_stones}\n"
            f"体力：{player.stamina}"
        )