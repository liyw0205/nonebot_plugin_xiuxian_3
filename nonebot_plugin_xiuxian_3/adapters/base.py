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
    router.register("开始合道", application.begin_dao_union)
    router.register("开始渡劫", application.begin_tribulation)
    router.register("选择结局", application.choose_ending, aliases=("终局选择",))
    router.register("终局战预览", application.preview_final_battle, aliases=("预览终局战",))
    router.register("创建终局战", application.create_final_battle)
    router.register("加入终局战", application.join_final_battle)
    router.register("开始终局战", application.start_final_battle)
    router.register("选择终局战", application.choose_final_battle)
    router.register("恢复终局战", application.recover_final_battle)
    router.register("取消终局战", application.cancel_final_battle)
    router.register("终局战回放", application.replay_final_battle)
    router.register("开始天劫试炼", application.start_tribulation_trial)
    router.register("结算天劫试炼", application.settle_tribulation_trial)
    router.register("恢复状态", application.recover_resources)
    router.register("突破预览", application.preview_breakthrough)
    router.register("开始突破", application.start_breakthrough)
    router.register("结算突破", application.settle_breakthrough)
    router.register("恢复虚弱", application.recover_weakness)
    router.register("恢复道基震荡", application.recover_foundation_shock)
    router.register("准备元婴", application.prepare_nascent_soul)
    router.register("化解心魔", application.resolve_heart_demon)
    router.register("恢复神魂疲劳", application.recover_soul_fatigue)
    router.register("选择领域", application.choose_domain)
    router.register("确认领域", application.confirm_domain)
    router.register("取消领域", application.cancel_domain)
    router.register("恢复领域裂痕", application.recover_domain_crack)
    router.register("生产预览", application.preview_recipe)
    router.register("开始生产", application.start_production)
    router.register("领取生产", application.complete_production)
    router.register("恢复生产", application.recover_production)
    router.register("开始终局配方", application.start_endgame_recipe)
    router.register("结算终局配方", application.settle_endgame_recipe)
    router.register("移动预览", application.preview_travel)
    router.register("前往", application.start_travel)
    router.register("前往雾隐洞天", application.start_cave_travel)
    router.register("结算移动", application.settle_travel)
    router.register("进入虚空航道", application.enter_void_route, aliases=("前往虚空航道", "虚空航行"))
    router.register("结算虚空航道", application.settle_void_route)
    router.register("开始探索", application.start_exploration)
    router.register("结算探索", application.settle_exploration)
    router.register("取消探索", application.cancel_exploration)
    router.register("开始训练战", application.start_training_battle, aliases=("训练战", "挑战训练傀儡"))
    router.register("领取战斗奖励", application.claim_battle_reward, aliases=("领取斗法奖励",))
    router.register("战斗回放", application.replay_battle, aliases=("斗法回放",))
    router.register("高阶任务", application.get_advanced_quests, aliases=("查看高阶任务", "任务进度"))
    router.register("完成领域委托", application.complete_domain_material_commission, aliases=("领域材料委托", "领域委托"))
    router.register("完成远古洞天任务", application.complete_ancient_domain_line, aliases=("远古洞天任务", "跨界探索", "探索边界秘境", "完成边界探索", "开始远古洞天探索"))
    router.register("开始跨界战", application.start_cross_realm_battle, aliases=("跨界战", "挑战跨界守门人"))
    router.register("开始界壁试炼", application.start_void_wall_trial, aliases=("界壁试炼", "开始虚空试炼"))
    router.register("探索档案遗迹", application.acquire_void_archive, aliases=("获取虚空档案", "探索虚空档案", "完成档案遗迹探索"))
    router.register("交付虚空档案", application.deliver_void_archive, aliases=("上交虚空档案", "交付档案"))
    router.register("领取化神许可", application.claim_soul_transformation_quest, aliases=("完成化神任务", "领取化神任务"))
    router.register("领取炼虚许可", application.claim_void_refining_quest, aliases=("完成炼虚任务", "领取炼虚任务"))
    router.register("记录合道主线", application.record_dao_union_mainline)
    router.register("开始合道挑战", application.start_dao_union_challenge)
    router.register("交付合道作品", application.deliver_dao_union_work)
    router.register("领取合道许可", application.claim_dao_union_quest)
    router.register("完成道源任务", application.complete_dao_origin_task)
    router.register("悬赏榜", application.list_bounties)
    router.register("接取悬赏", application.accept_bounty)
    router.register("领取悬赏", application.claim_bounty)
    router.register("主线道途", application.get_mainline_status, aliases=("主线", "主线状态"))
    router.register("开始主线", application.start_mainline)
    router.register("领取主线奖励", application.claim_mainline_reward)
    router.register("道源主线", application.get_dao_echoes_status)
    router.register("开始道源主线", application.start_dao_echoes_stage)
    router.register("领取道源主线奖励", application.claim_dao_echoes_stage)
    router.register("闭关预览", application.preview_retreat, aliases=("预览闭关",))
    router.register("开始闭关", application.start_retreat)
    router.register("结算闭关", application.settle_retreat)
    router.register("恢复闭关", application.recover_retreat)
    router.register("租住居所", application.lease_residence, aliases=("租房",))
    router.register("我的居所", application.get_residence, aliases=("居所状态",))
    router.register("灵田播种", application.plant_field, aliases=("播种",))
    router.register("灵田维护", application.maintain_field, aliases=("维护灵田",))
    router.register("灵田收获", application.harvest_field, aliases=("收获灵田",))
    router.register("我的灵田", application.get_field_profile, aliases=("灵田状态",))
    router.register("城镇委托", application.list_commissions, aliases=("委托榜",))
    router.register("接取委托", application.accept_commission, aliases=("接受委托",))
    router.register("交付委托", application.deliver_commission, aliases=("领取委托",))
    router.register("公共项目", application.list_projects, aliases=("公共建设", "项目榜"))
    router.register("贡献公共项目", application.contribute_project, aliases=("贡献项目", "建设项目"))
    router.register("结算公共项目", application.settle_project, aliases=("领取公共项目奖励", "结算项目"))
    router.register("运输预览", application.preview_route, aliases=("预览运输",))
    router.register("开始运输", application.start_route, aliases=("运输",))
    router.register("结算运输", application.settle_route)
    router.register("发布服务", application.publish_service, aliases=("发布服务订单",))
    router.register("接取服务", application.accept_service, aliases=("承接服务",))
    router.register("取消服务", application.cancel_service, aliases=("撤销服务",))
    router.register("结算服务", application.settle_service, aliases=("交付服务",))
    router.register("创建宗门", application.create_sect, aliases=("建立宗门",))
    router.register("申请入宗", application.apply_sect, aliases=("宗门申请",))
    router.register("宗门申请列表", application.list_sect_applications, aliases=("待审宗门申请",))
    router.register("审批入宗", application.review_sect_application, aliases=("审批宗门申请",))
    router.register("离开宗门", application.leave_sect, aliases=("离宗",))
    router.register("我的宗门", application.get_sect_profile, aliases=("宗门信息",))
    router.register("创建双人队伍", application.create_party, aliases=("创建探索队伍",))
    router.register("邀请入队", application.invite_party, aliases=("邀请队伍",))
    router.register("接受入队", application.accept_party, aliases=("同意入队",))
    router.register("拒绝入队", application.reject_party)
    router.register("确认入队", application.confirm_party, aliases=("队伍确认",))
    router.register("开始队伍战斗", application.start_party_battle, aliases=("队伍战斗",))
    router.register("结算队伍战斗", application.settle_party_battle)
    router.register("队伍战斗回放", application.replay_party_battle, aliases=("回放队伍战斗",))
    router.register("退出队伍", application.leave_party, aliases=("离开队伍",))
    router.register("我的队伍", application.get_party, aliases=("队伍状态",))
    router.register("邀请拜师", application.invite_mentor, aliases=("收徒邀请", "师徒邀请"))
    router.register("接受拜师", application.accept_mentor, aliases=("同意拜师", "拜师接受"))
    router.register("拒绝拜师", application.reject_mentor, aliases=("拜师拒绝",))
    router.register("师徒毕业", application.graduate_apprentice, aliases=("办理毕业", "徒弟毕业"))
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
    router.register("发布摆摊", application.create_market_order)
    router.register("购买摆摊", application.buy_market_order)
    router.register("取消摆摊", application.cancel_market_order)
    router.register("清理摆摊", application.expire_market_order)
    router.register("摆摊列表", application.list_market_orders)
    router.register("发布生产委托", application.create_production_commission)
    router.register("生产委托列表", application.list_production_commissions, aliases=("委托生产列表",))
    router.register("接取生产委托", application.accept_production_commission)
    router.register("交付生产委托", application.deliver_production_commission)
    router.register("确认生产委托", application.settle_production_commission)
    router.register("取消生产委托", application.cancel_production_commission)
    router.register("清理生产委托", application.expire_production_commission)
    router.register("恢复生产委托", application.recover_production_commission)
    router.register("灵泉事件", application.get_spirit_spring_event)
    router.register("领取灵泉事件奖励", application.claim_spirit_spring_event)
