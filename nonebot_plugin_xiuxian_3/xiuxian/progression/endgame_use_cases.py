"""Application services for the non-combat v0.6 endgame slice."""

from __future__ import annotations

from ...contracts import CommandContext, CommandResult
from ..repository import (
    AscensionRequirementError,
    CurrencyInsufficientError,
    DaoFruitChoiceError,
    DaoUnionRequirementError,
    EndingAlreadyChosenError,
    EndingInvalidError,
    MaterialInsufficientError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ThreeRealmReputationInsufficientError,
    TribulationCooldownError,
    TribulationDebtBlockedError,
    TribulationEntryRequirementError,
    TribulationTokenInsufficientError,
    TribulationTrialBusyError,
    TribulationTrialNotFoundError,
    TribulationTrialNotReadyError,
    TrialSequenceError,
    SQLitePlayerRepository,
)
from .endgame_rules import TRIAL_LABELS


class EndgameApplication:
    """Translate terminal progression commands into repository transactions."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.repository = repository

    @staticmethod
    def _operation_id(context: CommandContext, name: str) -> str:
        if context.operation_id:
            return context.operation_id
        request_key = context.message_id or context.request_id
        return f"{name}:{context.adapter}:{context.user_id}:{request_key}"

    @staticmethod
    def _display_name(player) -> str:
        return player.dao_name or "未命名"

    @staticmethod
    def _trial_key(value: str) -> str | None:
        aliases = {
            "身心劫": "trial.body_and_mind",
            "trial.body_and_mind": "trial.body_and_mind",
            "三界劫": "trial.three_realms",
            "trial.three_realms": "trial.three_realms",
            "道果劫": "trial.dao_choice",
            "trial.dao_choice": "trial.dao_choice",
        }
        return aliases.get(value)

    @staticmethod
    def _ending_key(value: str) -> str | None:
        aliases = {
            "飞升": "ascend",
            "ascend": "ascend",
            "飞升路": "ascend",
            "留界": "remain_in_world",
            "remain_in_world": "remain_in_world",
            "留界殿": "remain_in_world",
        }
        return aliases.get(value.strip().lower())

    @staticmethod
    def _failure(context: CommandContext, operation_id: str, code: str, message: str) -> CommandResult:
        return CommandResult(False, code, message, context.request_id, operation_id)

    async def begin_dao_union(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ENDGAME_COMMAND", "开始合道无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.begin_dao_union")
        try:
            record = await self.repository.begin_dao_union(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return self._failure(context, operation_id, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。")
        except DaoUnionRequirementError:
            return self._failure(context, operation_id, "DAO_UNION_REQUIREMENT_MISSING", "炼虚十层的道源任务、总修为或世界功勋尚未满足。")
        except MaterialInsufficientError:
            return self._failure(context, operation_id, "MATERIAL_INSUFFICIENT", "道果碎片不足，合道不会扣除其他资源。")
        except CurrencyInsufficientError:
            return self._failure(context, operation_id, "CURRENCY_INSUFFICIENT", "灵石不足，合道不会扣除其他资源。")
        except PlayerSuspendedError:
            return self._failure(context, operation_id, "PLAYER_SUSPENDED", "当前角色暂时不能合道。")
        except OperationConflictError:
            return self._failure(context, operation_id, "OPERATION_CONFLICT", "这次操作编号已经用于其他合道请求。")
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        return CommandResult(
            True,
            "DAO_UNION_STARTED",
            f"## 合道完成\n\n**{self._display_name(player)}**已进入合道 L1，三个道果线索已开启。",
            context.request_id,
            operation_id,
            data={"realm_key": player.realm_key, "realm_layer": player.realm_layer, "idempotent_replay": record.already_completed},
        )

    async def begin_tribulation(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_ENDGAME_COMMAND", "开始渡劫无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "progression.begin_tribulation")
        try:
            record = await self.repository.begin_tribulation(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return self._failure(context, operation_id, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。")
        except TribulationEntryRequirementError:
            return self._failure(context, operation_id, "TRIBULATION_ENTRY_REQUIREMENT_MISSING", "需要合道 L10 且总修为达到 8,998,960。")
        except PlayerSuspendedError:
            return self._failure(context, operation_id, "PLAYER_SUSPENDED", "当前角色暂时不能进入渡劫。")
        except OperationConflictError:
            return self._failure(context, operation_id, "OPERATION_CONFLICT", "这次操作编号已经用于其他渡劫请求。")
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        player = record.player
        return CommandResult(
            True,
            "TRIBULATION_STARTED",
            f"## 渡劫入境完成\n\n**{self._display_name(player)}**已进入渡劫 L1。先逐层修炼至 L3，再开始身心劫。",
            context.request_id,
            operation_id,
            data={"realm_key": player.realm_key, "realm_layer": player.realm_layer, "idempotent_replay": record.already_completed},
        )

    async def choose_ending(self, context: CommandContext) -> CommandResult:
        if len(context.command_args) != 1:
            return CommandResult(False, "INVALID_ENDING_COMMAND", "请使用 `选择结局 飞升` 或 `选择结局 留界`。", context.request_id)
        ending_key = self._ending_key(context.command_args[0])
        if ending_key is None:
            return CommandResult(False, "INVALID_ENDING_COMMAND", "结局只能选择飞升或留界。", context.request_id)
        operation_id = self._operation_id(context, "ascension.choose_ending")
        try:
            record = await self.repository.choose_ending(
                platform=context.adapter,
                platform_user_id=context.user_id,
                ending_key=ending_key,
                operation_id=operation_id,
            )
        except EndingInvalidError:
            return self._failure(context, operation_id, "INVALID_ENDING_COMMAND", "结局只能选择飞升或留界。")
        except AscensionRequirementError:
            return self._failure(context, operation_id, "ASCENSION_REQUIREMENT_MISSING", "尚未满足终局选择条件，或留界尚未锁定道果。")
        except EndingAlreadyChosenError:
            return self._failure(context, operation_id, "ENDING_ALREADY_CHOSEN", "终局已经选择，不能改选另一条结局。")
        except PlayerNotFoundError:
            return self._failure(context, operation_id, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。")
        except PlayerSuspendedError:
            return self._failure(context, operation_id, "PLAYER_SUSPENDED", "当前角色暂时不能选择终局。")
        except OperationConflictError:
            return self._failure(context, operation_id, "OPERATION_CONFLICT", "这次请求编号已经用于其他终局选择。")
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = "飞升" if record.ending_key == "ascend" else "留界"
        return CommandResult(
            True,
            "ENDING_CHOSEN",
            f"## 终局已定\n\n**{self._display_name(record.player)}**选择了 **{label}**。该选择不可更改。",
            context.request_id,
            operation_id,
            data={"ending_key": record.ending_key, "status": record.status, "realm_key": record.player.realm_key, "realm_layer": record.player.realm_layer, "idempotent_replay": record.already_completed},
        )

    async def start_trial(self, context: CommandContext) -> CommandResult:
        if not context.command_args or len(context.command_args) > 2:
            return CommandResult(False, "INVALID_TRIAL_COMMAND", "请使用 `开始天劫试炼 <身心劫|三界劫|道果劫> [道果键]`。", context.request_id)
        trial_key = self._trial_key(context.command_args[0])
        if trial_key is None or (trial_key != "trial.dao_choice" and len(context.command_args) != 1) or (trial_key == "trial.dao_choice" and len(context.command_args) != 2):
            return CommandResult(False, "INVALID_TRIAL_COMMAND", "身心劫、三界劫无需道果键；道果劫必须指定与主道途匹配的道果键。", context.request_id)
        choice_key = context.command_args[1] if len(context.command_args) == 2 else None
        operation_id = self._operation_id(context, "tribulation.start_trial")
        try:
            record = await self.repository.start_tribulation_trial(
                platform=context.adapter,
                platform_user_id=context.user_id,
                trial_key=trial_key,
                choice_key=choice_key,
                operation_id=operation_id,
            )
        except PlayerNotFoundError:
            return self._failure(context, operation_id, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。")
        except TrialSequenceError:
            return self._failure(context, operation_id, "TRIAL_SEQUENCE_INVALID", "天劫试炼必须按身心劫、三界劫、道果劫顺序完成。")
        except TribulationCooldownError:
            return self._failure(context, operation_id, "TRIBULATION_COOLDOWN", "该试炼失败冷却尚未结束。")
        except TribulationDebtBlockedError:
            return self._failure(context, operation_id, "TRIBULATION_DEBT_BLOCKED", "天劫债已达到 100，暂不能开启新的试炼。")
        except TribulationTrialBusyError:
            return self._failure(context, operation_id, "TRIBULATION_TRIAL_BUSY", "已有天劫试炼进行中，请先结算。")
        except TribulationTokenInsufficientError:
            return self._failure(context, operation_id, "TRIBULATION_TOKEN_INSUFFICIENT", "缺少天劫凭证，试炼未开始。")
        except ThreeRealmReputationInsufficientError:
            return self._failure(context, operation_id, "THREE_REALM_REPUTATION_INSUFFICIENT", "三界声望需各达到 2,000。")
        except DaoFruitChoiceError:
            return self._failure(context, operation_id, "DAO_FRUIT_PATH_MISMATCH", "道果必须与当前主道途匹配，且只能锁定一次。")
        except OperationConflictError:
            return self._failure(context, operation_id, "OPERATION_CONFLICT", "这次操作编号已经用于其他天劫试炼。")
        except PlayerSuspendedError:
            return self._failure(context, operation_id, "PLAYER_SUSPENDED", "当前角色暂时不能开始试炼。")
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = TRIAL_LABELS[record.trial_key]
        return CommandResult(
            True,
            "TRIAL_STARTED",
            f"## {label}已开始\n\n预计 30 分钟后发送 `结算天劫试炼`。凭证已锁定，重复请求会回放同一场试炼。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "trial_key": record.trial_key, "ends_at": record.ends_at, "idempotent_replay": record.already_completed},
        )

    async def settle_trial(self, context: CommandContext) -> CommandResult:
        if context.command_args:
            return CommandResult(False, "INVALID_TRIAL_COMMAND", "结算天劫试炼无需附加参数。", context.request_id)
        operation_id = self._operation_id(context, "tribulation.settle_trial")
        try:
            record = await self.repository.settle_tribulation_trial(
                platform=context.adapter, platform_user_id=context.user_id, operation_id=operation_id
            )
        except PlayerNotFoundError:
            return self._failure(context, operation_id, "PLAYER_NOT_FOUND", "还没有角色，请先发送 `开始修仙`。")
        except TribulationTrialNotFoundError:
            return self._failure(context, operation_id, "TRIBULATION_TRIAL_NOT_FOUND", "当前没有待结算的天劫试炼。")
        except TribulationTrialNotReadyError:
            return self._failure(context, operation_id, "TRIBULATION_TRIAL_NOT_READY", "天劫试炼尚未结束，请稍后再来。")
        except OperationConflictError:
            return self._failure(context, operation_id, "OPERATION_CONFLICT", "这次操作编号已经用于其他结算。")
        except PlayerSuspendedError:
            return self._failure(context, operation_id, "PLAYER_SUSPENDED", "当前角色暂时不能结算试炼。")
        except RepositoryBusyError:
            return CommandResult(False, "PERSISTENCE_BUSY", "仙缘簿暂时繁忙，请稍后再试。", context.request_id, operation_id, retryable=True)
        except Exception:
            return CommandResult(False, "PERSISTENCE_ERROR", "仙缘簿暂时不可用，请稍后再试。", context.request_id, operation_id, retryable=True)
        label = TRIAL_LABELS[record.trial_key]
        status = "成功" if record.success else "失败"
        return CommandResult(
            True,
            "TRIAL_SUCCEEDED" if record.success else "TRIAL_FAILED",
            f"## {label}结算{status}\n\n道果进度 +{record.reward_progress}，道源功勋 +{record.reward_merit}，天劫债 +{record.debt_delta}。",
            context.request_id,
            operation_id,
            data={"session_id": record.session_id, "trial_key": record.trial_key, "success": record.success, "roll_bp": record.roll_bp, "dao_fruit_progress": record.player.dao_fruit_progress, "ascension_merit": record.player.ascension_merit, "tribulation_debt": record.player.tribulation_debt, "dao_fruit_key": record.dao_fruit_key, "idempotent_replay": record.already_completed},
        )


__all__ = ["EndgameApplication"]
