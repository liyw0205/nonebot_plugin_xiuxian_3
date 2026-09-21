"""Application use cases for the player lifecycle."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    DaoNameTakenError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RenameCardRequiredError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .rules import (
    LOCATION_LABELS,
    QUALIFICATION_KEYS,
    QUALIFICATION_LABELS,
    STAGE_LABELS,
    STATUS_LABELS,
    validate_dao_name,
)


class PlayerApplication:
    """Coordinates player commands without exposing persistence details to adapters."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _invalid_context(context: CommandContext, message: str) -> CommandResult | None:
        try:
            context.validate()
        except ValueError:
            return CommandResult(
                ok=False,
                code="INVALID_CONTEXT",
                message="无法识别你的平台身份，请稍后重试。",
                request_id=context.request_id,
            )
        if not context.can_write_assets and message:
            return CommandResult(
                ok=False,
                code="INVALID_CONTEXT",
                message=message,
                request_id=context.request_id,
            )
        return None

    @staticmethod
    def _display_name(player) -> str:
        value = player.dao_name or "未命名"
        # Dao names are user input; escape Markdown before placing them in bold text.
        return (
            value.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("*", "\\*")
            .replace("_", "\\_")
            .replace("~", "\\~")
        )

    @staticmethod
    def _stage_text(stage: str) -> str:
        return STAGE_LABELS.get(stage, "修行阶段")

    @staticmethod
    def _status_text(status: str) -> str:
        return STATUS_LABELS.get(status, "未知状态")

    @staticmethod
    def _location_text(location_key: str) -> str:
        return LOCATION_LABELS.get(location_key, "未知地点")

    @staticmethod
    def _qualification_text(qualification: dict[str, int]) -> str:
        if not qualification:
            return "未生成"
        return "\n".join(
            f"- **{QUALIFICATION_LABELS[key]}**：{qualification.get(key, 0)}"
            for key in QUALIFICATION_KEYS
        )

    async def create_player(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context, "当前事件缺少可验证的消息身份，无法创建角色。")
        if invalid is not None:
            return invalid
        if len(context.command_args) > 1:
            return CommandResult(
                False,
                "INVALID_DAO_NAME",
                "道号只能是一段不超过 7 个字的名称。",
                context.request_id,
            )
        try:
            dao_name = validate_dao_name(
                context.command_args[0] if context.command_args else "",
                allow_empty=True,
            )
        except ValueError:
            return CommandResult(
                False,
                "INVALID_DAO_NAME",
                "道号不能为空格，长度不能超过 7 个字。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "player.create")
        try:
            record = await self.repository.create_player(
                platform=context.adapter,
                platform_user_id=context.user_id,
                scene_id=context.scene_id,
                nickname=context.nickname,
                dao_name=dao_name,
                operation_id=operation_id,
            )
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他输入，请重新发起操作。", context.request_id, operation_id)
        except DaoNameTakenError:
            return CommandResult(False, "DAO_NAME_TAKEN", "这个道号已经被其他道友使用了，请换一个。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能写入。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        if record.created:
            code = "PLAYER_CREATED"
            message = (
                "## 身份登记完成\n\n"
                f"**{self._display_name(player)}**，你的修仙身份已经建立。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                "- **当前阶段**：新用户\n"
                "- **灵石**：0\n\n"
                "> 下一步：发送 `寻仙问道`，开始生成你的入道资质。\n"
                "> 尚未取道号？之后可使用 `修仙改名 道号`，首次改名无需改名卡。"
            )
        else:
            code = "PLAYER_ALREADY_EXISTS"
            message = (
                "## 角色已经存在\n\n"
                f"**{self._display_name(player)}**，你已经登记过修仙身份。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **当前阶段**：{self._stage_text(player.stage)}\n\n"
                "> 可发送 `我的状态` 查看详细资料。"
            )
        return CommandResult(
            ok=True,
            code=code,
            message=message,
            request_id=context.request_id,
            operation_id=operation_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "stage": player.stage,
                "status": player.status,
                "location_key": player.location_key,
                "rule_version": player.rule_version,
                "spirit_stones": player.spirit_stones,
                "qualification": player.qualification,
                "idempotent_replay": record.already_completed,
            },
        )

    async def start_seeking(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context, "当前事件缺少可验证的消息身份，无法执行指令。")
        if invalid is not None:
            return invalid
        operation_id = self._operation_id(context, "player.start_seeking")
        try:
            record = await self.repository.start_seeking(
                platform=context.adapter,
                platform_user_id=context.user_id,
                scene_id=context.scene_id,
                nickname=context.nickname,
                root_affinity=context.command_args[0] if context.command_args else "",
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "尚未登记角色，请先发送“开始修仙”。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能写入。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他输入，请重新发起操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        if record.created:
            message = (
                "## 寻仙问道成功\n\n"
                f"**{self._display_name(player)}**，你已踏入凡人阶段。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **阶段**：{self._stage_text(player.stage)}\n"
                f"- **灵石**：{player.spirit_stones}\n\n"
                "### 六项资质\n\n"
                + self._qualification_text(player.qualification)
                + "\n\n> 下一步：查看 `我的状态`，确认当前修仙信息。"
            )
            code = "SEEKING_STARTED"
        else:
            message = (
                "## 已完成寻仙问道\n\n"
                f"**{self._display_name(player)}**，你的入道资质已经保存。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **当前阶段**：{self._stage_text(player.stage)}\n"
                f"- **灵石**：{player.spirit_stones}\n\n"
                "> 可发送 `我的状态` 查看完整资料。"
            )
            code = "SEEKING_ALREADY_DONE"
        return CommandResult(
            ok=True,
            code=code,
            message=message,
            request_id=context.request_id,
            operation_id=operation_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "stage": player.stage,
                "status": player.status,
                "location_key": player.location_key,
                "rule_version": player.rule_version,
                "spirit_stones": player.spirit_stones,
                "qualification": player.qualification,
                "idempotent_replay": record.already_completed,
            },
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        try:
            context.validate()
        except ValueError:
            return CommandResult(False, "INVALID_CONTEXT", "无法识别你的平台身份，请稍后重试。", context.request_id)
        try:
            player = await self.repository.get_player(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        if player is None:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送“开始修仙”。", context.request_id)
        return CommandResult(
            ok=True,
            code="PROFILE_READ",
            message=(
                "## 我的修仙信息\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **阶段**：{self._stage_text(player.stage)}\n"
                f"- **状态**：{self._status_text(player.status)}\n"
                f"- **位置**：{self._location_text(player.location_key)}\n"
                f"- **灵石**：{player.spirit_stones}\n"
                "\n### 六项资质\n\n"
                f"{self._qualification_text(player.qualification)}"
            ),
            request_id=context.request_id,
            data={
                "player_id": player.player_id,
                "dao_name": player.dao_name,
                "platform": player.platform,
                "stage": player.stage,
                "status": player.status,
                "location_key": player.location_key,
                "rule_version": player.rule_version,
                "spirit_stones": player.spirit_stones,
                "qualification": player.qualification,
                "path_key": player.path_key,
                "subprofession_key": player.subprofession_key,
            },
        )

    async def rename_player(self, context: CommandContext) -> CommandResult:
        invalid = self._invalid_context(context, "当前事件缺少可验证的消息身份，无法修改道号。")
        if invalid is not None:
            return invalid
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_DAO_NAME",
                "请使用 `修仙改名 道号`，道号长度不能超过 7 个字。",
                context.request_id,
            )
        try:
            dao_name = validate_dao_name(context.command_args[0])
        except ValueError:
            return CommandResult(
                False,
                "INVALID_DAO_NAME",
                "道号不能为空格，长度不能超过 7 个字。",
                context.request_id,
            )
        operation_id = self._operation_id(context, "player.rename")
        try:
            record = await self.repository.rename_player(
                platform=context.adapter,
                platform_user_id=context.user_id,
                dao_name=dao_name,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能修改道号。", context.request_id, operation_id)
        except DaoNameTakenError:
            return CommandResult(False, "DAO_NAME_TAKEN", "这个道号已经被其他道友使用了，请换一个。", context.request_id, operation_id)
        except RenameCardRequiredError:
            return CommandResult(False, "RENAME_CARD_REQUIRED", "再次修改道号需要消耗一张改名卡。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他输入，请重新发起操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        if record.changed:
            message = (
                "## 道号已立\n\n"
                f"你的道号是 **{self._display_name(record.player)}**。\n\n"
                "> 首次取道号无需改名卡；之后再次修改时需要改名卡。"
            )
            code = "DAO_NAME_CHANGED"
        else:
            message = f"## 道号未变化\n\n当前道号仍是 **{self._display_name(record.player)}**。"
            code = "DAO_NAME_UNCHANGED"
        return CommandResult(
            True,
            code,
            message,
            context.request_id,
            operation_id,
            data={
                "player_id": record.player.player_id,
                "dao_name": record.player.dao_name,
                "idempotent_replay": record.already_completed,
            },
        )
