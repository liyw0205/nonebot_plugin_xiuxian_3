"""Application use cases for the player lifecycle."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentBundle
from ..progression.rules import segment_for_layer
from ..repository import (
    DaoNameTakenError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RenameCardRequiredError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .intro_use_cases import IntroApplication
from .cultivation_use_cases import CultivationApplication
from .path_rules import path_name, subprofession_name
from .rules import (
    LOCATION_LABELS,
    QUALIFICATION_KEYS,
    QUALIFICATION_LABELS,
    REALM_LABELS,
    realm_display_name,
    STAGE_LABELS,
    STATUS_LABELS,
    validate_dao_name,
)
from ..utils.player import player_profile_values, player_projection
from ..stats.presentation import PROFILE_STATS, stat_lines
from ..content import ContentError
from ..utils.text import command_link


class PlayerApplication:
    """Coordinates player commands without exposing persistence details to adapters."""

    def __init__(self, repository: SQLitePlayerRepository, content: ContentBundle | None = None):
        self.repository = repository
        self.content = content
        self.intro = IntroApplication(repository)
        self.cultivation = CultivationApplication(repository, content)

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

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
    def _realm_text(
        realm_key: str,
        layer: int,
        *,
        content: ContentBundle | None = None,
    ) -> str:
        labels = dict(REALM_LABELS)
        if content is not None:
            record = content.get("realm", realm_key, include_locked=False)
            if record is not None and isinstance(record.get("name"), str):
                labels[realm_key] = record["name"]
        text = realm_display_name(realm_key, layer, labels=labels)
        if layer:
            try:
                text += f"（{segment_for_layer(int(layer))}）"
            except (TypeError, ValueError):
                pass
        return text

    def _path_text(self, path_key: str | None, subprofession_key: str | None) -> str:
        if not path_key:
            return "未选择"
        try:
            name = path_name(path_key, self.content)
        except ContentError:
            return "未知道途"
        if subprofession_key:
            try:
                name += f"·{subprofession_name(subprofession_key, path_key, self.content)}"
            except ContentError:
                name += "·辅修"
        return name

    @staticmethod
    def _qualification_text(qualification: dict[str, int]) -> str:
        if not qualification:
            return "未生成"
        return "\n".join(
            f"- **{QUALIFICATION_LABELS[key]}**：{qualification.get(key, 0)}"
            for key in QUALIFICATION_KEYS
        )

    async def create_player(self, context: CommandContext) -> CommandResult:
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
                "**身份登记完成**\n\n"
                f"**{self._display_name(player)}**，你的修仙身份已经建立。\n\n"
                f"- **道号**：{self._display_name(player)} · {command_link('改名', '修仙改名')}\n"
                "- **当前阶段**：新用户\n"
                "- **灵石**：0\n\n"
                "下一步可寻仙问道，了解自己的入道资质。首次取道号无需改名卡。"
            )
        else:
            code = "PLAYER_ALREADY_EXISTS"
            message = (
                "**角色已经存在**\n\n"
                f"**{self._display_name(player)}**，你已经登记过修仙身份。\n\n"
                f"- **道号**：{self._display_name(player)} · {command_link('改名', '修仙改名')}\n"
                f"- **当前阶段**：{self._stage_text(player.stage)}\n\n"
                f"{command_link('我的状态', '我的状态')}可查看详细资料。"
            )
        return CommandResult(
            ok=True,
            code=code,
            message=message,
            request_id=context.request_id,
            operation_id=operation_id,
            actions=(CommandAction("寻仙问道", "寻仙问道", enter=True),) if record.created else (),
            data={
                **player_projection(
                    player,
                    ("player_id", "dao_name", "stage", "status", "location_key", "spirit_stones", "qualification"),
                ),
                "idempotent_replay": record.already_completed,
            },
        )

    async def start_seeking(self, context: CommandContext) -> CommandResult:
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
            return CommandResult(False, "PLAYER_NOT_FOUND", f"尚未登记角色，先{command_link('开始修仙', '开始修仙')}，再来寻仙。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色处于暂停状态，暂时不能写入。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求的操作编号已用于其他输入，请重新发起操作。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except ContentError:
            return CommandResult(False, "CONTENT_INVALID", "启程礼暂未备妥，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

        player = record.player
        if record.created:
            message = (
                "**寻仙问道成功**\n\n"
                f"**{self._display_name(player)}**，你已踏入凡人阶段。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **阶段**：{self._stage_text(player.stage)}\n"
                f"- **灵石**：{player.spirit_stones}\n\n"
                f"- **体力**：{player.stamina}/{player.stamina_max}\n"
                f"- **精力**：{player.energy}/{player.energy_max}\n"
                "- **初始物资**：启程所需物资已收入囊中\n\n"
                "**六项资质**\n\n"
                + self._qualification_text(player.qualification)
                + "\n\n接下来先读世界说明，开启凡人引导。"
            )
            code = "SEEKING_STARTED"
        else:
            message = (
                "## 已完成寻仙问道\n\n"
                f"**{self._display_name(player)}**，你的入道资质已经保存。\n\n"
                f"- **道号**：{self._display_name(player)}\n"
                f"- **当前阶段**：{self._stage_text(player.stage)}\n"
                f"- **灵石**：{player.spirit_stones}\n\n"
                f"{command_link('我的状态', '我的状态')}可查看完整资料。"
            )
            code = "SEEKING_ALREADY_DONE"
        return CommandResult(
            ok=True,
            code=code,
            message=message,
            request_id=context.request_id,
            operation_id=operation_id,
            actions=(CommandAction("阅读世界说明", "完成引导 阅读", enter=True),) if record.created else (),
            data={
                **player_projection(
                    player,
                    (
                        "player_id",
                        "dao_name",
                        "stage",
                        "status",
                        "location_key",
                        "spirit_stones",
                        "stamina",
                        "stamina_max",
                        "energy",
                        "energy_max",
                        "inventory",
                        "realm_key",
                        "realm_layer",
                        "total_cultivation",
                        "qualification",
                    ),
                ),
                "reward": dict(record.reward or {}),
                "idempotent_replay": record.already_completed,
            },
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        try:
            player, stats = await self.repository.get_player_profile(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        if player is None:
            return CommandResult(False, "PLAYER_NOT_FOUND", f"还没有角色，先{command_link('开始修仙', '开始修仙')}，写下你的道号。", context.request_id)
        values = player_profile_values(player)
        stats_summary = (
            "\n\n### 周身气象\n\n" + "\n".join(stat_lines(stats["derived_stats"], PROFILE_STATS))
            if stats
            else ""
        )
        soul_summary = (
            f"- **神魂**：{values['soul_power']}/{values['soul_power_max']}\n"
            f"- **领域能量**：{values['domain_charge']}/{values['domain_charge_max']}\n"
            f"- **污染**：{values['pollution']}\n"
            if values["realm_key"] in {"nascent_soul", "soul_transformation", "void_refining"}
            else ""
        )
        domain_summary = (
            f"- **领域**：{values['domain_key'] or '未选择'}\n"
            f"- **领域力量**：{values['domain_power']}\n"
            f"- **领域抵抗**：{values['realm_resistance_bp']} bp\n"
            f"- **领域裂痕**：{values['domain_crack_until'] or '无'}\n"
            if values["realm_key"] in {"soul_transformation", "void_refining"}
            else ""
        )
        void_summary = (
            f"- **虚力**：{values['void_power']}/{values['void_power_max']}\n"
            f"- **空间抗性**：{values['space_resistance_bp']} bp\n"
            f"- **虚空航道发现**：{values['void_route_count']}\n"
            f"- **虚空不稳定**：{values['void_instability_until'] or '无'}\n"
            if values["realm_key"] == "void_refining" else ""
        )
        endgame_summary = (
            f"- **道果进度**：{values['dao_fruit_progress']}\n"
            f"- **道源功勋**：{values['ascension_merit']}\n"
            f"- **天劫债**：{values['tribulation_debt']}\n"
            f"- **道果**：{values['dao_fruit_key'] or '未锁定'}\n"
            if values["realm_key"] in {"dao_union", "tribulation"} or values["endgame_status"] != "none"
            else ""
        )
        next_step = ""
        if player.stage == "new_user":
            next_step = command_link("寻仙问道", "寻仙问道") + "，了解资质并领取启程物资。"
        elif player.stage in {"mortal", "seeker"}:
            next_step = self.intro._guide_hint(player)
        return CommandResult(
            ok=True,
            code="PROFILE_READ",
            message=(
                "**我的修仙信息**\n\n"
                f"- **道号**：{self._display_name(player)} · {command_link('改名', '修仙改名')}\n"
                f"- **阶段**：{self._stage_text(values['stage'])}\n"
                f"- **状态**：{self._status_text(values['status'])}\n"
                f"- **位置**：{self._location_text(values['location_key'])}\n"
                f"- **境界**：{self._realm_text(values['realm_key'], values['realm_layer'], content=self.content)}\n"
                f"- **灵石**：{values['spirit_stones']}\n"
                f"- **体力**：{values['stamina']}/{values['stamina_max']}\n"
                f"- **精力**：{values['energy']}/{values['energy_max']}\n"
                f"- **道途**：{self._path_text(values['path_key'], values['subprofession_key'])}\n"
                f"- **境内修为**：{values['cultivation']}\n"
                f"- **总修为**：{values['total_cultivation']}\n"
                f"- **道基质量**：{values['foundation_quality']}\n"
                f"- **世界功勋**：{values['world_merit']}\n"
                f"- **虚空功勋**：{values['void_merit']}\n"
                f"- **联盟积分**：{values['alliance_points']}\n"
                f"{soul_summary}"
                f"{domain_summary}"
                f"{void_summary}"
                f"{endgame_summary}"
                "\n### 六项资质\n\n"
                f"{self._qualification_text(values['qualification'])}"
                f"{stats_summary}"
                f"\n\n### 凡人引导\n\n- **进度**：{len(set(values['intro_flags']))}/3"
                + ("\n\n" + next_step if next_step else "")
            ),
            request_id=context.request_id,
            data={**values, "stats": stats},
        )

    async def rename_player(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(
                False,
                "INVALID_DAO_NAME",
                f"用{command_link('修仙改名', '修仙改名')}填写新道号，长度不能超过 7 个字。",
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
            return CommandResult(False, "PLAYER_NOT_FOUND", f"还没有角色，先{command_link('开始修仙', '开始修仙')}，再来取道号。", context.request_id, operation_id)
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

    async def complete_intro(self, context: CommandContext) -> CommandResult:
        return await self.intro.complete_intro(context)

    async def travel_intro(self, context: CommandContext, destination: str) -> CommandResult:
        return await self.intro.travel_intro(context, destination)

    async def enter_cultivation(self, context: CommandContext) -> CommandResult:
        return await self.cultivation.enter_cultivation(context)
