"""Application commands for the v0.1 routine slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    AchievementAlreadyClaimedError,
    AchievementInvalidError,
    AchievementNotCompletedError,
    CheckinAlreadyClaimedError,
    CurrencyInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    RoutineMakeupDateError,
    RoutineMakeupLimitError,
    RoutineMakeupNotEligibleError,
    SevenDayGoalAlreadyClaimedError,
    SevenDayGoalInvalidError,
    SevenDayGoalNotCompletedError,
    SevenDayGoalNotOpenError,
    SevenDayNotStartedError,
    HonorTitleClosedError,
    HonorTitleNotFoundError,
    SpiritTreeCooldownError,
    SpiritTreeNotReadyError,
    SpiritTreeWateredError,
    SQLitePlayerRepository,
)
from .rules import (
    ACHIEVEMENTS,
    CHECKIN_ACTIVITY,
    FATE_TICKET,
    HONOR_TITLES,
    TREE_HARVEST_ACTIVITY,
    TREE_SEED,
    TREE_WATER_ACTIVITY,
    honor_title,
    parse_iso_date,
)


class RoutineApplication:
    """Coordinates routine commands and Markdown responses."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, operation_name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{operation_name}:{context.adapter}:{context.user_id}:{request_key}"

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

    @staticmethod
    def _reward_text(reward: dict[str, int]) -> str:
        labels = {
            "spirit_stones": "灵石",
            "energy": "精力",
            "local_reputation": "地方名望",
            FATE_TICKET: "机缘签",
            TREE_SEED: "灵木种子",
            "item.food.coarse_spirit_rice": "粗糙灵米",
            "item.herb.blood_grass": "止血草",
            "item.mat.array_sand": "阵砂",
        }
        return "、".join(
            f"{labels.get(key, '奖励')} ×{value}"
            for key, value in reward.items()
            if value
        ) or "无"

    @staticmethod
    def _honor_reward_text(reward: dict[str, int | str]) -> str:
        labels = {
            "local_reputation": "地方名望",
            "service_reputation": "服务信誉",
            "title_key": "称号",
        }
        parts: list[str] = []
        for key, value in reward.items():
            if key == "title_key":
                try:
                    parts.append(f"称号「{honor_title(str(value)).label}」")
                except ValueError:
                    parts.append("称号")
            else:
                parts.append(f"{labels.get(key, '奖励')} +{value}")
        return "、".join(parts) or "无"

    @staticmethod
    def _resolve_achievement(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        value = args[0].strip()
        if value.isdigit():
            index = int(value)
            if 1 <= index <= len(ACHIEVEMENTS):
                return ACHIEVEMENTS[index - 1].key
            return None
        for definition in ACHIEVEMENTS:
            if value in {definition.key, definition.label}:
                return definition.key
        return None

    @staticmethod
    def _resolve_title(args: tuple[str, ...]) -> str | None:
        if len(args) != 1:
            return None
        value = args[0].strip()
        if value.isdigit():
            index = int(value)
            if 1 <= index <= len(HONOR_TITLES):
                return HONOR_TITLES[index - 1].key
            return None
        for definition in HONOR_TITLES:
            if value in {definition.key, definition.label}:
                return definition.key
        return None

    @staticmethod
    def _honor_state_text(state: str) -> str:
        return {
            "claimed": "已领取",
            "claimable": "可领取",
            "pending": "待完成",
            "content_closed": "内容未开放",
        }.get(state, "待完成")

    async def claim_daily(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "道历问安无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "routine.checkin.daily")
        try:
            record = await self.repository.claim_daily(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except CheckinAlreadyClaimedError:
            return CommandResult(False, "CHECKIN_ALREADY_CLAIMED", "今日已经问安过了，明日再来。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能进行道历问安。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他道历操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        extra = ""
        if FATE_TICKET in record.reward:
            extra = "\n\n> 连续问安七日，额外获得 **机缘签 ×1**。"
        return CommandResult(
            True,
            "DAILY_CHECKIN_CLAIMED",
            (
                "## 道历问安完成\n\n"
                f"**{self._display_name(record.player)}**今日问安已记档。\n\n"
                f"- **连续问安**：{record.consecutive_days} 日\n"
                f"- **获得**：{self._reward_text(record.reward)}\n"
                f"- **精力**：{record.player.energy}/{record.player.energy_max}"
                f"{extra}"
            ),
            context.request_id,
            operation_id,
            data={
                "target_date": record.target_date,
                "reward": record.reward,
                "consecutive_days": record.consecutive_days,
                "idempotent_replay": record.already_completed,
            },
        )

    async def makeup_daily(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "请使用 `补录道历 YYYY-MM-DD`。", context.request_id)
        try:
            target_date = parse_iso_date(context.command_args[0])
        except ValueError:
            return CommandResult(False, "INVALID_MAKEUP_DATE", "只能补录本月最近 3 日内漏掉的道历。", context.request_id)
        operation_id = self._operation_id(context, "routine.makeup.daily")
        try:
            record = await self.repository.makeup_daily(
                platform=context.adapter,
                platform_user_id=context.user_id,
                target_date=target_date.isoformat(),
                operation_id=operation_id,
            )
        except RoutineMakeupNotEligibleError:
            return CommandResult(False, "MAKEUP_NOT_ELIGIBLE", "这一天已经问安或补录过了，不能重复补录。", context.request_id, operation_id)
        except RoutineMakeupDateError:
            return CommandResult(False, "INVALID_MAKEUP_DATE", "只能补录本月最近 3 个已过去的业务日。", context.request_id, operation_id)
        except RoutineMakeupLimitError:
            return CommandResult(False, "MAKEUP_LIMIT_REACHED", "本月补录次数已用尽，最多补录 2 次。", context.request_id, operation_id)
        except CurrencyInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "补录道历需要 30 灵石，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能补录道历。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他道历操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "DAILY_CHECKIN_MADE_UP",
            (
                "## 道历补录完成\n\n"
                f"**{self._display_name(record.player)}**已补录 **{record.target_date}**。\n\n"
                f"- **消耗灵石**：{record.spirit_stones_spent}\n"
                f"- **获得**：{self._reward_text(record.reward)}\n\n"
                "> 补录只恢复当天奖励，不计入连续问安。"
            ),
            context.request_id,
            operation_id,
            data={"target_date": record.target_date, "reward": record.reward, "idempotent_replay": record.already_completed},
        )

    async def water_spirit_tree(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "浇灌灵木无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, TREE_WATER_ACTIVITY)
        try:
            record = await self.repository.water_spirit_tree(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except SpiritTreeWateredError:
            return CommandResult(False, "SPIRIT_TREE_ALREADY_WATERED", "今日已经浇灌过灵木了，明日再来。", context.request_id, operation_id)
        except SpiritTreeCooldownError:
            return CommandResult(False, "SPIRIT_TREE_COOLDOWN", "灵木正在休养，冷却结束后才能再次培育。", context.request_id, operation_id)
        except ResourceInsufficientError:
            return CommandResult(False, "RESOURCE_INSUFFICIENT", "浇灌灵木需要 2 点精力，未扣除任何资源。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能培育灵木。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵木操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        status_text = "已成熟，等待收获" if record.status == "ready" else f"已浇灌 {record.water_count}/7 次"
        return CommandResult(
            True,
            "SPIRIT_TREE_WATERED",
            (
                "## 灵木浇灌完成\n\n"
                f"**{self._display_name(record.player)}**的灵木{status_text}。\n\n"
                f"- **消耗精力**：{record.energy_spent}\n"
                f"- **剩余精力**：{record.player.energy}/{record.player.energy_max}\n\n"
                "> 灵木成熟后发送 `收获灵木`。"
            ),
            context.request_id,
            operation_id,
            data={"status": record.status, "water_count": record.water_count, "idempotent_replay": record.already_completed},
        )

    async def harvest_spirit_tree(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "收获灵木无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, TREE_HARVEST_ACTIVITY)
        try:
            record = await self.repository.harvest_spirit_tree(
                platform=context.adapter,
                platform_user_id=context.user_id,
                operation_id=operation_id,
            )
        except SpiritTreeNotReadyError:
            return CommandResult(False, "SPIRIT_TREE_NOT_READY", "灵木还未成熟，完成 7 次浇灌后才能收获。", context.request_id, operation_id)
        except SpiritTreeCooldownError:
            return CommandResult(False, "SPIRIT_TREE_COOLDOWN", "灵木正在休养，冷却结束后才能再次培育。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能收获灵木。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他灵木操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SPIRIT_TREE_HARVESTED",
            (
                "## 灵木收获完成\n\n"
                f"**{self._display_name(record.player)}**收获了一轮灵木灵蕴。\n\n"
                f"- **获得**：{self._reward_text(record.reward)}\n"
                f"- **灵石**：{record.player.spirit_stones}\n\n"
                "> 灵木进入 24 小时休养，之后可以重新浇灌。"
            ),
            context.request_id,
            operation_id,
            data={"reward": record.reward, "cooldown_until": record.cooldown_until, "idempotent_replay": record.already_completed},
        )

    @staticmethod
    def _seven_day_state_text(state: str) -> str:
        return {
            "claimed": "已领取",
            "claimable": "可领取",
            "pending": "待完成",
            "locked": "尚未开启",
            "content_closed": "内容未开放",
        }.get(state, "待完成")

    async def get_seven_day_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "查看七日入道无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_seven_day_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except SevenDayNotStartedError:
            return CommandResult(False, "SEVEN_DAY_NOT_STARTED", "请先发送 `寻仙问道`，再开启七日入道。", context.request_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看七日入道。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = [
            "## 七日入道",
            "",
            f"**{self._display_name(record.player)}** · 第 {record.current_day}/7 业务日",
            f"- **开始日期**：{record.start_date}",
            "",
        ]
        goals = []
        for goal in record.goals:
            state_text = self._seven_day_state_text(goal.state)
            lines.append(f"- **D{goal.day_number} {goal.label}**：{state_text}（{goal.target_date}）")
            goals.append(
                {
                    "day": goal.day_number,
                    "label": goal.label,
                    "target_date": goal.target_date,
                    "state": goal.state,
                    "reward": goal.reward,
                }
            )
        lines.append("")
        lines.append("> 已完成的目标可发送 `领取七日目标 日数` 领取奖励；目标可以补做，但不会重置七日进度。")
        return CommandResult(
            True,
            "SEVEN_DAY_STATUS",
            "\n".join(lines),
            context.request_id,
            data={
                "start_date": record.start_date,
                "current_day": record.current_day,
                "status": record.status,
                "goals": goals,
            },
        )

    async def claim_seven_day_goal(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "请使用 `领取七日目标 日数`，日数为 1 到 7。", context.request_id)
        try:
            day_number = int(context.command_args[0])
        except ValueError:
            day_number = 0
        operation_id = self._operation_id(context, "routine.claim_seven_day_goal")
        try:
            record = await self.repository.claim_seven_day_goal(
                platform=context.adapter,
                platform_user_id=context.user_id,
                day_number=day_number,
                operation_id=operation_id,
            )
        except SevenDayGoalInvalidError:
            return CommandResult(False, "INVALID_ROUTINE_COMMAND", "七日目标日数只能是 1 到 7。", context.request_id, operation_id)
        except SevenDayNotStartedError:
            return CommandResult(False, "SEVEN_DAY_NOT_STARTED", "请先发送 `寻仙问道`，再开启七日入道。", context.request_id, operation_id)
        except SevenDayGoalNotOpenError:
            return CommandResult(False, "SEVEN_DAY_GOAL_NOT_OPEN", "这一天的目标尚未开启，请按业务日顺序完成。", context.request_id, operation_id)
        except SevenDayGoalAlreadyClaimedError:
            return CommandResult(False, "SEVEN_DAY_ALREADY_CLAIMED", "这一天的七日目标奖励已经领取过了。", context.request_id, operation_id)
        except SevenDayGoalNotCompletedError:
            return CommandResult(False, "SEVEN_DAY_GOAL_NOT_COMPLETED", "目标尚未完成，或它依赖的内容暂未开放。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取七日目标奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他七日目标，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "SEVEN_DAY_GOAL_CLAIMED",
            (
                f"## 七日目标已领取\n\n"
                f"**{self._display_name(record.player)}**完成了第 **D{record.day_number}** 天目标。\n\n"
                f"- **获得**：{self._reward_text(record.reward)}\n"
                f"- **目标日期**：{record.target_date}\n\n"
                "> 七日进度按首次寻仙问道日期计算，补做不会重置进度。"
            ),
            context.request_id,
            operation_id,
            data={
                "day": record.day_number,
                "target_date": record.target_date,
                "reward": record.reward,
                "campaign_complete": record.campaign_complete,
                "idempotent_replay": record.already_completed,
            },
        )

    async def get_honor_status(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_HONOR_COMMAND", "查看功业录无需附加参数。", context.request_id)
        try:
            record = await self.repository.get_honor_status(
                platform=context.adapter,
                platform_user_id=context.user_id,
            )
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能查看功业录。", context.request_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, retryable=True)
        lines = [
            "## 功业录",
            "",
            f"**{self._display_name(record.player)}**的修行记录",
            "",
            "### 功业",
        ]
        achievements: list[dict[str, object]] = []
        for index, item in enumerate(record.achievements, start=1):
            state_text = self._honor_state_text(item.state)
            lines.append(f"- **{index}. {item.label}**：{state_text}")
            achievements.append(
                {
                    "index": index,
                    "achievement_key": item.achievement_key,
                    "label": item.label,
                    "state": item.state,
                    "reward": item.reward,
                }
            )
        lines.extend(["", "### 称号", ""])
        titles: list[dict[str, object]] = []
        for index, item in enumerate(record.titles, start=1):
            title_definition = next(
                definition for definition in HONOR_TITLES if definition.key == item.title_key
            )
            if item.acquired:
                state_text = "已佩戴" if item.equipped else "已获得"
            elif item.source_operation_id is None:
                state_text = "内容未开放" if title_definition.closed else "未获得"
            else:
                state_text = "已获得"
            lines.append(f"- **{index}. {item.label}**：{state_text}")
            titles.append(
                {
                    "index": index,
                    "title_key": item.title_key,
                    "label": item.label,
                    "acquired": item.acquired,
                    "equipped": item.equipped,
                }
            )
        lines.extend(
            [
                "",
                "> 发送 `领取功业 序号` 领取可领取的功业奖励；发送 `佩戴称号 序号` 更换展示称号。",
            ]
        )
        return CommandResult(
            True,
            "HONOR_STATUS",
            "\n".join(lines),
            context.request_id,
            data={
                "equipped_title_key": record.equipped_title_key,
                "titles": titles,
                "achievements": achievements,
            },
        )

    async def claim_achievement(self, context: CommandContext) -> CommandResult:
        achievement_key = self._resolve_achievement(context.command_args)
        if achievement_key is None:
            return CommandResult(False, "INVALID_HONOR_COMMAND", "请使用 `领取功业 序号`，序号可在 `功业录` 中查看。", context.request_id)
        operation_id = self._operation_id(context, "routine.claim_achievement")
        try:
            record = await self.repository.claim_achievement(
                platform=context.adapter,
                platform_user_id=context.user_id,
                achievement_key=achievement_key,
                operation_id=operation_id,
            )
        except AchievementInvalidError:
            return CommandResult(False, "INVALID_HONOR_COMMAND", "未找到这项功业。", context.request_id, operation_id)
        except AchievementNotCompletedError:
            return CommandResult(False, "ACHIEVEMENT_NOT_COMPLETED", "这项功业尚未完成。", context.request_id, operation_id)
        except AchievementAlreadyClaimedError:
            return CommandResult(False, "ACHIEVEMENT_ALREADY_CLAIMED", "这项功业的奖励已经领取过了。", context.request_id, operation_id)
        except HonorTitleClosedError:
            return CommandResult(False, "CONTENT_CLOSED", "这项功业依赖的内容尚未开放。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能领取功业奖励。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他功业，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "ACHIEVEMENT_CLAIMED",
            (
                "## 功业奖励已领取\n\n"
                f"**{self._display_name(record.player)}**完成了 **{record.label}**。\n\n"
                f"- **获得**：{self._honor_reward_text(record.reward)}\n\n"
                "> 奖励已写入功业记录，重复领取不会再次发放。"
            ),
            context.request_id,
            operation_id,
            data={
                "achievement_key": record.achievement_key,
                "label": record.label,
                "reward": record.reward,
                "source_operation_id": record.source_operation_id,
                "idempotent_replay": record.already_completed,
            },
        )

    async def equip_title(self, context: CommandContext) -> CommandResult:
        title_key = self._resolve_title(context.command_args)
        if title_key is None:
            return CommandResult(False, "INVALID_HONOR_COMMAND", "请使用 `佩戴称号 序号`，序号可在 `功业录` 中查看。", context.request_id)
        operation_id = self._operation_id(context, "routine.equip_title")
        try:
            record = await self.repository.equip_title(
                platform=context.adapter,
                platform_user_id=context.user_id,
                title_key=title_key,
                operation_id=operation_id,
            )
        except HonorTitleNotFoundError:
            return CommandResult(False, "TITLE_NOT_FOUND", "你还没有获得这个称号。", context.request_id, operation_id)
        except PlayerNotFoundError:
            return CommandResult(False, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。", context.request_id, operation_id)
        except PlayerSuspendedError:
            return CommandResult(False, "PLAYER_SUSPENDED", "当前角色暂时不能更换称号。", context.request_id, operation_id)
        except OperationConflictError:
            return CommandResult(False, "OPERATION_CONFLICT", "这次请求编号已用于其他称号操作，请重新发起。", context.request_id, operation_id)
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        return CommandResult(
            True,
            "TITLE_EQUIPPED",
            (
                "## 称号已更换\n\n"
                f"**{self._display_name(record.player)}**当前展示称号为 **{record.label}**。"
            ),
            context.request_id,
            operation_id,
            data={
                "title_key": record.title_key,
                "label": record.label,
                "idempotent_replay": record.already_completed,
            },
        )


__all__ = ["RoutineApplication"]
