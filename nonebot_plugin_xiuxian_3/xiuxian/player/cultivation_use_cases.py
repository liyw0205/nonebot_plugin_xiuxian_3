"""Application use case for the first path selection."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    OperationConflictError,
    PathAlreadySelectedError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
    SubprofessionRequiredError,
)
from .path_rules import (
    PATH_LABELS,
    SUBPROFESSION_LABELS,
    resolve_path,
    resolve_subprofession,
)
from .rules import STAGE_LABELS


class CultivationApplication:
    """Selects the first path and settles its fixed entry reward."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"player.enter_cultivation:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    async def enter_cultivation(self, context: CommandContext) -> CommandResult:
        path_key, subprofession_key, error = self._parse_args(context.command_args)
        if error:
            return CommandResult(False, "INVALID_PATH", error, context.request_id)
        operation_id = self._operation_id(context)
        try:
            record = await self.repository.enter_cultivation(
                platform=context.adapter,
                platform_user_id=context.user_id,
                path_key=path_key,
                subprofession_key=subprofession_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerStageConflictError:
            return CommandResult(False, "PLAYER_STAGE_CONFLICT", "完成三项凡人引导后，才能选择道途入道。", context.request_id, operation_id)
        except PathAlreadySelectedError:
            return CommandResult(False, "PATH_ALREADY_SELECTED", "你已经选择过首要道途，不能重复选择。", context.request_id, operation_id)
        except SubprofessionRequiredError:
            return CommandResult(False, "SUBPROFESSION_REQUIRED", "辅修必须同时选择炼丹、炼器或布阵。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能入道。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他选择，请重新发起入道。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        path_name = PATH_LABELS[path_key]
        subprofession_name = SUBPROFESSION_LABELS.get(subprofession_key or "")
        reward_hint = "基础功法与对应试用技能"
        if path_key == "support":
            reward_hint += f"，以及{SUBPROFESSION_LABELS[subprofession_key or '']}工具"
        message = (
            "## 入道完成\n\n"
            f"**{self._display_name(player)}**已选择 **{path_name}**，正式踏入修行之路。\n\n"
            f"- **道途**：{path_name}\n"
            + (f"- **主辅修**：{subprofession_name}\n" if subprofession_name else "")
            + f"- **境界**：感气一层\n"
            f"- **灵石**：{player.spirit_stones}\n"
            f"- **入道所得**：{reward_hint}\n\n"
            "> 下一步：查看 `我的状态`，确认你的修行构筑。"
        )
        return CommandResult(
            True,
            "CULTIVATION_ENTERED",
            message,
            context.request_id,
            operation_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "stage": player.stage,
                "realm_key": player.realm_key,
                "realm_layer": player.realm_layer,
                "path_key": player.path_key,
                "subprofession_key": player.subprofession_key,
                "spirit_stones": player.spirit_stones,
                "inventory": player.inventory,
                "idempotent_replay": record.already_completed,
            },
        )

    @staticmethod
    def _parse_args(args: tuple[str, ...]) -> tuple[str, str | None, str | None]:
        if not args or len(args) > 2:
            return "", None, "请使用 `选择道途 体修`，辅修还需追加 `炼丹`、`炼器` 或 `布阵`。"
        path_key = resolve_path(args[0])
        if path_key is None:
            return "", None, "未知道途，可选：体修、法修、器修、魔修、妖修、辅修。"
        subprofession_key = None
        if len(args) == 2:
            subprofession_key = resolve_subprofession(args[1])
            if subprofession_key is None:
                return "", None, "主辅修只能选择炼丹、炼器或布阵。"
            if path_key != "support":
                return "", None, "只有辅修需要同时选择生产方向。"
        elif path_key == "support":
            return path_key, None, None
        return path_key, subprofession_key, None


__all__ = ["CultivationApplication"]
