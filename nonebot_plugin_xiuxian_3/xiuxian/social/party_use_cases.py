"""Application services for the two-player exploration party slice."""

from __future__ import annotations

from ...contracts import CommandAction, CommandContext, CommandResult
from ..content import ContentError, bundled_content
from ..utils.text import command_link
from ..repository import (
    OperationConflictError,
    PartyAlreadyMemberError,
    PartyInvitationExpiredError,
    PartyInvitationNotFoundError,
    PartyLocationMismatchError,
    PartyNotFoundError,
    PartyPermissionDeniedError,
    PartyStateConflictError,
    PartyBattleBusyError,
    PartyBattleNotFoundError,
    PartyBattleNotReadyError,
    PartyBattlePermissionError,
    PartyBattleRequirementError,
    PartyBattleResourceError,
    PartyBattleDailyLimitError,
    BoundaryRealmRequirementError,
    BoundaryRealmResourceError,
    CrossRealmPartyRequirementError,
    FactionReputationInsufficientError,
    PollutionTooHighError,
    SoulExhaustionActiveError,
    SoulPowerInsufficientError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    SQLitePlayerRepository,
)
from .party_rules import (
    PARTY_TYPE_ARENA_TRIO,
    PARTY_TYPE_BEAST_REALM,
    PARTY_TYPE_DEMON_REALM,
    PARTY_TYPE_BOUNDARY_REALM,
    PARTY_TYPE_SECRET_REALM_BOUNDARY,
    PARTY_TYPE_SECRET_REALM_ANCIENT,
    PARTY_TYPE_SECRET_REALM_VOID_RUINS,
    PARTY_TYPE_SECRET_REALM_TIME_FORT,
    PARTY_TYPE_STANDARD_PVE,
    PARTY_TYPE_THREE_REALMS_TOWER_DUO,
)


class PartyApplication:
    """Translate party state transitions into adapter-neutral commands."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository
        self.content = repository.content if repository.content is not None else bundled_content()

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _members_data(record) -> list[dict[str, str | None]]:
        return [
            {
                "player_id": member.player_id,
                "platform_user_id": member.platform_user_id,
                "dao_name": member.dao_name,
                "role": member.role,
                "status": member.status,
                "confirmed_at": member.confirmed_at,
            }
            for member in record.members
        ]

    @classmethod
    def _data(cls, record) -> dict[str, object]:
        return {
            "party_id": record.party_id,
            "party_type": record.party_type,
            "status": record.status,
            "ready": record.ready,
            "leader_player_id": record.leader_player_id,
            "location_key": record.location_key,
            "confirmation_deadline": record.confirmation_deadline,
            "distribution_key": record.distribution_key,
            "members": cls._members_data(record),
            "idempotent_replay": record.already_completed,
        }

    @staticmethod
    def _summary(record) -> str:
        members = "、".join(member.dao_name for member in record.members if member.status in {"active", "invited"}) or "暂无成员"
        state = "已就绪" if record.ready else ("已解散" if record.status == "disbanded" else "等待确认")
        return f"- **队伍号**：`{record.party_id}`\n- **状态**：{state}\n- **地点**：`{record.location_key}`\n- **成员**：{members}\n- **确认截止**：{record.confirmation_deadline}"

    async def create_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type="exploration_pair", title="双人探索队伍", invite_hint="一名同地点道友")

    async def create_arena_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_ARENA_TRIO, title="三人竞技队伍", invite_hint="两名同地点道友")

    async def create_boundary_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_BOUNDARY_REALM, title="界隙队伍", invite_hint="一至四名同地点、已完成三界主线的元婴道友")

    async def create_boundary_rift_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_SECRET_REALM_BOUNDARY,
            title="界隙裂隙秘境队伍",
            invite_hint="一至四名同地点、已完成三界主线的元婴道友",
        )

    async def create_ancient_domain_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_SECRET_REALM_ANCIENT,
            title="远古洞天秘境队伍",
            invite_hint="两名同在远古洞天、已达化神 L1 的道友",
        )

    async def create_void_ruins_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_SECRET_REALM_VOID_RUINS,
            title="虚空遗迹秘境队伍",
            invite_hint="一至四名同在虚空档案遗迹、已达炼虚 L1 并携有虚空锚的道友",
        )

    async def create_time_fort_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_SECRET_REALM_TIME_FORT,
            title="时序堡垒秘境队伍",
            invite_hint="一至四名同在虚空档案遗迹、已达炼虚 L1 并持有时序许可的道友",
        )

    async def create_demon_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_DEMON_REALM, title="魔渊队伍", invite_hint="一至四名同在堕落遗迹的元婴道友")

    async def create_beast_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(context, party_type=PARTY_TYPE_BEAST_REALM, title="万兽队伍", invite_hint="一至四名同在万兽山的元婴道友")

    async def create_standard_pve_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_STANDARD_PVE,
            title="多人副本队伍",
            invite_hint="三至四名同地点道友",
        )

    def _reward_text(self, reward: dict[str, int]) -> str:
        labels = {"cultivation": "修为", "spirit_stones": "灵石", "world_merit": "功勋", "soul_power": "神魂"}
        parts = []
        for key, amount in reward.items():
            item = self.content.get("item", key, include_locked=True) if key.startswith("item.") else None
            parts.append(f"{item['name'] if item else labels.get(key, key)} ×{amount}")
        return "、".join(parts) or "无"

    async def preview_standard_party(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "多人副本预览无需附加参数。", context.request_id)
        try:
            view = await self.repository.preview_standard_party(platform=context.adapter, platform_user_id=context.user_id)
        except Exception as exc:
            return self._party_battle_error(context, "", exc)
        if not view["supported"]:
            names = "、".join(row["name"] for row in view["locations"])
            return CommandResult(True, "PARTY_BATTLE_PREVIEW", f"此处没有开放的多人副本。可前往：{names}。", context.request_id, data=view)
        realm = self.content.require("realm", view["required_realm"], include_locked=True)
        reason_labels = {"unavailable": "当前不可行动", "unconfirmed": "尚未确认", "location": "不在集结地", "realm": "境界不足",
                         "stamina": "体力不足", "energy": "精力不足", "daily_limit": "今日次数已用尽", "busy": "另有行程或战斗",
                         "no_party": "尚未组队", "party_type": "须使用多人副本队伍", "not_leader": "须由队长开战",
                         "not_ready": "队伍尚未就绪", "expired": "队伍确认已过期，请重新集结", "member_count": "人数不足或超限"}
        limit = f"每日 {view['daily_limit']} 次（UTC 零时重置）" if view["daily_limit"] else "不设每日入场次数"
        lines = ["## 多人副本战备", f"对手：{view['enemy_name']}｜{realm['name']} {view['required_layer']} 层起",
                 f"人数：{view['min_members']} 至 {view['max_members']} 人，全员确认、同地集结。",
                 f"每人入场：体力 {view['cost']['stamina']}、精力 {view['cost']['energy']}；{limit}。",
                 f"每名获奖成员：{self._reward_text(view['reward'])}。"]
        for member in view["members"]:
            state = "、".join(reason_labels[key] for key in member["blockers"]) or "已备妥"
            quota = f"，今日已出战 {member['daily_used']}/{view['daily_limit']}" if view["daily_limit"] else ""
            lines.append(f"- {member['name']}：{state}；体力 {member['stamina']}、精力 {member['energy']}{quota}")
        if view["blockers"]:
            lines.append("待办：" + "、".join(reason_labels[key] for key in view["blockers"]) + "。")
        if view["consumers"]:
            lines.append("材料去处：" + "、".join(command_link(row["name"], f"{row['command']} {row['name']}" if row["command"] == "生产预览" else row["command"]) for row in view["consumers"]) + "。")
        if view["daily_limit"]:
            lines.append("开战即计次，战败或超时不退入场消耗且不发胜利材料。断线后任一参战成员可结算原战斗。")
        actions = [CommandAction("我的队伍", "我的队伍")]
        if "no_party" in view["blockers"]:
            actions.insert(0, CommandAction("创建队伍", "创建多人副本队伍"))
        elif view["can_start"]:
            actions.insert(0, CommandAction("开始战斗", "开始队伍战斗"))
        return CommandResult(True, "PARTY_BATTLE_PREVIEW", "\n\n".join(lines), context.request_id, data=view, actions=tuple(actions))

    async def create_three_realms_tower_duo_party(self, context: CommandContext) -> CommandResult:
        return await self._create_party(
            context,
            party_type=PARTY_TYPE_THREE_REALMS_TOWER_DUO,
            title="三界塔双人队伍",
            invite_hint="一名同地点道友",
        )

    async def _create_party(self, context: CommandContext, *, party_type: str, title: str, invite_hint: str) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", f"创建{title}无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.create_party")
        try:
            record = await self.repository.create_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
                party_type=party_type,
            )
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "你已经在队伍或待处理邀请中。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能创建队伍。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "队伍必须在对应副本地点创建。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "PARTY_CREATED",
            f"## {title}已创建\n\n" + self._summary(record) + f"\n\n请邀请{invite_hint}。",
            context.request_id,
            operation_id,
            data=self._data(record),
        )

    async def invite_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `邀请入队 用户ID`。", context.request_id)
        operation_id = self._operation_id(context, "social.invite_party")
        try:
            record = await self.repository.invite_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_ref=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyPermissionDeniedError:
            return CommandResult(False, "PARTY_PERMISSION_DENIED", "只有队长可以邀请成员。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "双方必须位于同一地点。", context.request_id, operation_id)
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "目标已在队伍或其他待处理邀请中。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_MEMBER_CAP", "队伍已满或不再接受邀请。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "没有找到目标角色。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "目标角色暂时不可加入队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_INVITED", "## 已发出入队邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def accept_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `接受入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.accept_party")
        try:
            record = await self.repository.accept_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyInvitationExpiredError:
            return CommandResult(False, "PARTY_CONFIRMATION_EXPIRED", "这份入队邀请已经过期。", context.request_id, operation_id)
        except PartyInvitationNotFoundError:
            return CommandResult(False, "PARTY_INVITATION_NOT_FOUND", "没有找到这份入队邀请。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "你已不在队伍创建时的地点。", context.request_id, operation_id)
        except PartyAlreadyMemberError:
            return CommandResult(False, "PARTY_ALREADY_MEMBER", "你已经在队伍或其他待处理邀请中。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能接受邀请。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_JOINED", "## 已接受入队邀请\n\n" + self._summary(record) + "\n\n请发送 `确认入队 队伍号` 完成双方确认。", context.request_id, operation_id, data=self._data(record))

    async def reject_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `拒绝入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.reject_party")
        try:
            record = await self.repository.reject_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyInvitationNotFoundError:
            return CommandResult(False, "PARTY_INVITATION_NOT_FOUND", "没有找到这份入队邀请。", context.request_id, operation_id)
        except PartyInvitationExpiredError:
            return CommandResult(False, "PARTY_CONFIRMATION_EXPIRED", "这份入队邀请已经过期。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能处理队伍邀请。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_INVITATION_REJECTED", "## 已拒绝入队邀请\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def confirm_party(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "请使用 `确认入队 队伍号`。", context.request_id)
        operation_id = self._operation_id(context, "social.confirm_party")
        try:
            record = await self.repository.confirm_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=context.command_args[0],
                operation_id=operation_id,
            )
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你不在这支队伍中。", context.request_id, operation_id)
        except PartyLocationMismatchError:
            return CommandResult(False, "PARTY_LOCATION_MISMATCH", "所有成员必须位于队伍创建时的地点。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_STATE_CONFLICT", "当前队伍不能确认。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能确认队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        message = "## 队伍已就绪\n\n" if record.ready else "## 队伍确认已记录\n\n"
        if record.ready:
            message += "全体成员已确认；队长可以发起队伍战斗。"
        else:
            message += "等待其他成员确认。"
        return CommandResult(True, "PARTY_READY" if record.ready else "PARTY_CONFIRMED", message + "\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    @staticmethod
    def _party_battle_error(context: CommandContext, operation_id: str, exc: Exception) -> CommandResult:
        errors = {
            ContentError: ("CONTENT_INVALID", "此处副本资料有误，暂时不能启程。"),
            BoundaryRealmRequirementError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员必须满足元婴、三界主线和界隙地点要求。"),
            BoundaryRealmResourceError: ("SOUL_CRYSTAL_INSUFFICIENT", "队伍需要全员 30 体力，并由队长支付 1 枚神魂晶。"),
            CrossRealmPartyRequirementError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员未满足该跨界副本的地点、资格或体力要求。"),
            FactionReputationInsufficientError: ("BATTLE_CROSS_REALM_REQUIREMENT_MISSING", "队伍成员的对应阵营声望不足。"),
            PollutionTooHighError: ("POLLUTION_TOO_HIGH", "队伍成员污染过高，不能进入魔渊副本。"),
            SoulExhaustionActiveError: ("SOUL_EXHAUSTION_ACTIVE", "队伍成员的神魂疲劳尚未结束，暂时不能进入跨界副本。"),
            SoulPowerInsufficientError: ("BATTLE_SOUL_POWER_INSUFFICIENT", "队伍成员神魂不足，暂时不能进入跨界副本。"),
            PartyBattlePermissionError: ("PARTY_BATTLE_PERMISSION_DENIED", "只有队长可以发起队伍战斗，已确认成员可以结算。"),
            PartyBattleResourceError: ("PARTY_BATTLE_RESOURCE_INSUFFICIENT", "有成员入场体力或精力不足，请查看 `多人副本预览`。"),
            PartyBattleDailyLimitError: ("PARTY_BATTLE_DAILY_LIMIT", "有成员今日出战次数已用尽，请查看 `多人副本预览`。"),
            PartyBattleRequirementError: ("PARTY_BATTLE_REQUIREMENT_MISSING", "队伍人数、确认、地点或境界尚未满足，请查看 `多人副本预览`。"),
            PartyBattleBusyError: ("PARTY_BATTLE_BUSY", "队伍或成员已有锁定中的战斗资产。"),
            PartyBattleNotFoundError: ("PARTY_BATTLE_NOT_FOUND", "当前没有可查看的队伍战斗。"),
            PartyBattleNotReadyError: ("PARTY_BATTLE_NOT_READY", "队伍战斗仍在由服务器自动推进。"),
            PartyNotFoundError: ("PARTY_NOT_FOUND", "当前没有可用的队伍。"),
            OperationConflictError: ("OPERATION_CONFLICT", "此事与先前安排不合，请重新起意。"),
            PlayerNotFoundError: ("PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。"),
            PlayerSuspendedError: ("PLAYER_SUSPENDED", "当前角色暂时不能进行队伍战斗。"),
            RepositoryBusyError: ("PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。"),
        }
        for error_type, (code, message) in errors.items():
            if isinstance(exc, error_type):
                return CommandResult(False, code, message, context.request_id, operation_id, retryable=error_type is RepositoryBusyError)
        return CommandResult(False, "PERSISTENCE_ERROR", "队伍战斗会话暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)

    async def start_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "开始队伍战斗最多接收一个队伍号。", context.request_id)
        operation_id = self._operation_id(context, "battle.party.start")
        party_id = context.command_args[0] if context.command_args else None
        try:
            started = await self.repository.start_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                party_id=party_id,
                operation_id=operation_id,
            )
            resolved = await self.repository.settle_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=started.battle_id,
                operation_id=f"{operation_id}:settle",
            )
        except Exception as exc:
            return self._party_battle_error(context, operation_id, exc)
        return await self._party_battle_result(context, operation_id, resolved)

    async def settle_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "结算队伍战斗最多接收一个战斗编号。", context.request_id)
        operation_id = self._operation_id(context, "battle.party.settle")
        try:
            resolved = await self.repository.settle_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=context.command_args[0] if context.command_args else None,
                operation_id=operation_id,
            )
        except Exception as exc:
            return self._party_battle_error(context, operation_id, exc)
        return await self._party_battle_result(context, operation_id, resolved)

    async def _party_battle_result(self, context: CommandContext, operation_id: str, record) -> CommandResult:
        outcome = "胜利" if record.outcome == "won" else ("失败" if record.outcome == "lost" else "超时")
        replay = await self.repository.replay_party_battle(platform=context.adapter, platform_user_id=context.user_id, battle_id=record.battle_id)
        member_rewards = [{"player_id": member["player_id"], "name": member.get("dao_name", member["player_id"]),
                           "reward": record.rewards.get(str(member["database_id"]), {})} for member in replay.snapshot["members"]]
        reward_text = "\n".join(f"- {member['name']}：{self._reward_text(member['reward'])}" for member in member_rewards)
        actions = [CommandAction("战斗回放", f"队伍战斗回放 {record.battle_id}"), CommandAction("战备预览", "多人副本预览")]
        if any(key.startswith("item.") for reward in record.rewards.values() for key in reward):
            actions.append(CommandAction("城镇委托", "城镇委托"))
        return CommandResult(
            True,
            "PARTY_BATTLE_SETTLED",
            f"## 队伍战斗结束\n\n- **结果**：{outcome}\n- **回合**：{record.round_no}\n\n成员所得：\n{reward_text}\n\n{command_link('查看行动回放', f'队伍战斗回放 {record.battle_id}')}。",
            context.request_id,
            operation_id,
            data={
                "battle_id": record.battle_id,
                "party_id": record.party_id,
                "enemy_key": record.enemy_key,
                "outcome": record.outcome,
                "round_no": record.round_no,
                "rewards": record.rewards,
                "member_rewards": member_rewards,
                "contributions": record.contributions,
                "reward_order": list(record.reward_order),
                "reward_rolls": record.reward_rolls,
                "idempotent_replay": record.already_completed,
            },
            actions=tuple(actions),
        )

    async def replay_party_battle(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) > 1:
            return CommandResult(False, "INVALID_PARTY_BATTLE_COMMAND", "队伍战斗回放最多接收一个战斗编号。", context.request_id)
        try:
            record = await self.repository.replay_party_battle(
                platform=context.adapter,
                platform_user_id=context.user_id,
                battle_id=context.command_args[0] if context.command_args else None,
            )
        except Exception as exc:
            return self._party_battle_error(context, "", exc)
        enemy = record.snapshot.get("enemy", {})
        return CommandResult(
            True,
            "PARTY_BATTLE_REPLAY",
            f"## 队伍战斗回放\n\n- **战斗**：`{record.battle_id}`\n- **敌人**：{enemy.get('label', record.enemy_key)}\n- **结果**：{record.result.get('outcome', '进行中')}\n- **行动数**：{len(record.actions)}",
            context.request_id,
            data={"battle_id": record.battle_id, "party_id": record.party_id, "enemy_key": record.enemy_key, "result": record.result, "actions": list(record.actions)},
        )

    async def leave_party(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "退出队伍无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "social.leave_party")
        try:
            record = await self.repository.leave_party(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你当前不在可退出的队伍中。", context.request_id, operation_id)
        except PartyStateConflictError:
            return CommandResult(False, "PARTY_STATE_CONFLICT", "队伍战斗进行中，结算前不能退出队伍。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能退出队伍。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "此事已有安排，请重新起意。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(True, "PARTY_LEFT", "## 已退出队伍\n\n" + self._summary(record), context.request_id, operation_id, data=self._data(record))

    async def get_party(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_PARTY_COMMAND", "我的队伍无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_party(platform=context.adapter, platform_user_id=context.user_id)
        except PartyNotFoundError:
            return CommandResult(False, "PARTY_NOT_FOUND", "你当前没有队伍或待处理邀请。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看队伍。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        return CommandResult(True, "PARTY_PROFILE", "## 我的队伍\n\n" + self._summary(record), context.request_id, data=self._data(record))


__all__ = ["PartyApplication"]
