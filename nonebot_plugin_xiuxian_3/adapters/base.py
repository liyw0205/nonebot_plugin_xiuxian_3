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
    router.register("完成引导", application.complete_intro)
    router.register("前往近郊", lambda context: application.travel_intro(context, "近郊"))
    router.register("前往灵泉谷", lambda context: application.travel_intro(context, "灵泉谷"))
    router.register("返回新手城", lambda context: application.travel_intro(context, "新手城"))
    router.register("选择道途", application.enter_cultivation)
    router.register("开始修炼", application.start_cultivation)
    router.register("结算修炼", application.settle_cultivation)
    router.register("恢复修炼", application.recover_cultivation)
    router.register("取消修炼", application.cancel_cultivation)
    router.register("晋升境界", application.advance_layer, aliases=("境界晋升",))
    router.register("恢复状态", application.recover_resources)
    router.register("突破预览", application.preview_breakthrough)
    router.register("开始突破", application.start_breakthrough)
    router.register("结算突破", application.settle_breakthrough)
    router.register("恢复虚弱", application.recover_weakness)
    router.register("生产预览", application.preview_recipe)
    router.register("开始生产", application.start_production)
    router.register("领取生产", application.complete_production)
    router.register("恢复生产", application.recover_production)
    router.register("移动预览", application.preview_travel)
    router.register("前往", application.start_travel)
    router.register("前往雾隐洞天", application.start_cave_travel)
    router.register("结算移动", application.settle_travel)
    router.register("开始探索", application.start_exploration)
    router.register("结算探索", application.settle_exploration)
    router.register("取消探索", application.cancel_exploration)
    router.register("悬赏榜", application.list_bounties)
    router.register("接取悬赏", application.accept_bounty)
    router.register("领取悬赏", application.claim_bounty)
    router.register("主线道途", application.get_mainline_status, aliases=("主线", "主线状态"))
    router.register("开始主线", application.start_mainline)
    router.register("领取主线奖励", application.claim_mainline_reward)
    router.register("闭关预览", application.preview_retreat, aliases=("预览闭关",))
    router.register("开始闭关", application.start_retreat)
    router.register("结算闭关", application.settle_retreat)
    router.register("恢复闭关", application.recover_retreat)
    router.register("租住居所", application.lease_residence, aliases=("租房",))
    router.register("我的居所", application.get_residence, aliases=("居所状态",))
    router.register("体质预览", application.preview_constitution, aliases=("预览体质",))
    router.register("选择体质", application.select_constitution)
    router.register("我的体质", application.get_constitution, aliases=("体质状态",))
    router.register("重塑体质", application.reshape_constitution)
    router.register("道脉预览", application.preview_talents, aliases=("天赋预览",))
    router.register("我的道脉", application.get_talent_profile, aliases=("我的天赋", "天赋状态"))
    router.register("解锁天赋", application.unlock_talent, aliases=("学习天赋",))
    router.register("神通预览", application.preview_skills, aliases=("预览神通",))
    router.register("我的神通", application.get_skill_profile, aliases=("神通状态",))
    router.register("参悟神通", application.train_skill, aliases=("升级神通",))
    router.register("法器预览", application.preview_equipment, aliases=("预览法器",))
    router.register("重铸预览", application.preview_refinement, aliases=("预览重铸",))
    router.register("强化法器", application.temper_equipment)
    router.register("重铸法器", application.refine_equipment)
    router.register("道历问安", application.claim_daily, aliases=("每日问安", "签到"))
    router.register("补录道历", application.makeup_daily, aliases=("补签到",))
    router.register("浇灌灵木", application.water_spirit_tree, aliases=("灵木浇灌", "浇水"))
    router.register("收获灵木", application.harvest_spirit_tree, aliases=("灵木收获",))
    router.register("七日入道", application.get_seven_day_status, aliases=("七日目标", "入道七日"))
    router.register("领取七日目标", application.claim_seven_day_goal, aliases=("领取七日任务", "领取七日入道"))
    router.register("功业录", application.get_honor_status, aliases=("我的功业", "我的称号"))
    router.register("领取功业", application.claim_achievement, aliases=("领取成就",))
    router.register("佩戴称号", application.equip_title, aliases=("装备称号",))
    router.register("兑换密令", application.redeem_code, aliases=("领取密令", "使用密令"))
    router.register("我的道契", application.get_dao_contract_status, aliases=("道契状态",))
    router.register("激活道契", application.activate_dao_contract)
    router.register("领取道契", application.claim_dao_contract)
    router.register("机缘寻宝", application.roll_fate_pool, aliases=("寻宝", "机缘抽奖"))
    router.register("问道行卷", application.get_wayfaring_status, aliases=("行卷状态",))
    router.register("开始行卷", application.start_wayfaring)
    router.register("领取行卷", application.claim_wayfaring_level)
