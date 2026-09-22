"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..contracts import CommandContext, CommandResult, validate_command_identity
from .player.use_cases import PlayerApplication
from .production.use_cases import ProductionApplication
from .progression.use_cases import ProgressionApplication
from .progression.breakthrough.use_cases import BreakthroughApplication
from .world.use_cases import WorldApplication
from .exploration.use_cases import ExplorationApplication
from .adventures.use_cases import AdventuresApplication
from .adventures.mainline_use_cases import AdventuresMainlineApplication
from .advancement.use_cases import AdvancementApplication
from .advancement.constitution_use_cases import ConstitutionApplication
from .advancement.talent_use_cases import TalentApplication
from .advancement.skill_use_cases import SkillApplication
from .advancement.equipment_use_cases import EquipmentApplication
from .livelihood.use_cases import LivelihoodApplication
from .routine.use_cases import RoutineApplication
from .routine.gacha_use_cases import GachaApplication
from .routine.wayfaring_use_cases import WayfaringApplication
from .repository import SQLitePlayerRepository


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.player = PlayerApplication(repository)
        self.progression = ProgressionApplication(repository)
        self.breakthrough = BreakthroughApplication(repository)
        self.production = ProductionApplication(repository)
        self.world = WorldApplication(repository)
        self.exploration = ExplorationApplication(repository)
        self.adventures = AdventuresApplication(repository)
        self.mainline = AdventuresMainlineApplication(repository)
        self.advancement = AdvancementApplication(repository)
        self.constitution = ConstitutionApplication(repository)
        self.talent = TalentApplication(repository)
        self.skill = SkillApplication(repository)
        self.equipment = EquipmentApplication(repository)
        self.livelihood = LivelihoodApplication(repository)
        self.routine = RoutineApplication(repository)
        self.gacha = GachaApplication(repository)
        self.wayfaring = WayfaringApplication(repository)

    async def _invoke(
        self,
        context: CommandContext,
        handler: Callable[[], Awaitable[CommandResult]],
        *,
        require_write: bool = True,
        write_message: str = "当前事件不允许执行此操作。",
    ) -> CommandResult:
        """Run an application use case after one shared identity check."""

        invalid = validate_command_identity(
            context,
            require_write=require_write,
            write_message=write_message,
        )
        if invalid is not None:
            return invalid
        return await handler()

    async def create_player(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.create_player(context),
            write_message="当前事件缺少可验证的消息身份，无法创建角色。",
        )

    async def start_seeking(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.start_seeking(context),
            write_message="当前事件缺少可验证的消息身份，无法执行指令。",
        )

    async def get_profile(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.player.get_profile(context), require_write=False)

    async def rename_player(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.rename_player(context),
            write_message="当前事件缺少可验证的消息身份，无法修改道号。",
        )

    async def complete_intro(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.complete_intro(context),
            write_message="当前事件不允许进行引导结算。",
        )

    async def travel_intro(self, context: CommandContext, destination: str) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.travel_intro(context, destination),
            write_message="当前事件不允许进行移动。",
        )

    async def enter_cultivation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.player.enter_cultivation(context),
            write_message="当前事件不允许进行入道结算。",
        )

    async def start_cultivation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.start_cultivation(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def settle_cultivation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.settle_cultivation(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def recover_cultivation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.recover_cultivation(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def cancel_cultivation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.cancel_cultivation(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def advance_layer(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.advance_layer(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def recover_resources(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.progression.recover_resources(context),
            write_message="当前事件不允许进行修炼结算。",
        )

    async def preview_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.breakthrough.preview_breakthrough(context), require_write=False)

    async def start_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.start_breakthrough(context),
            write_message="当前事件不允许进行突破结算。",
        )

    async def settle_breakthrough(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.settle_breakthrough(context),
            write_message="当前事件不允许进行突破结算。",
        )

    async def recover_weakness(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.recover_weakness(context),
            write_message="当前事件不允许进行突破结算。",
        )

    async def recover_foundation_shock(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.recover_foundation_shock(context),
            write_message="当前事件不允许进行突破结算。",
        )

    async def preview_recipe(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.production.preview_recipe(context), require_write=False)

    async def start_production(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.start_production(context),
            write_message="当前事件不允许锁定生产资产。",
        )

    async def complete_production(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.complete_production(context),
            write_message="当前事件不允许领取生产结果。",
        )

    async def recover_production(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.recover_production(context),
            write_message="当前事件不允许恢复生产订单。",
        )

    async def preview_travel(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.world.preview_travel(context), require_write=False)

    async def start_travel(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.start_travel(context),
            write_message="当前事件不允许开始移动。",
        )

    async def start_cave_travel(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.start_travel(context, "cave.mist_grotto"),
            write_message="当前事件不允许开始移动。",
        )

    async def settle_travel(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.settle_travel(context),
            write_message="当前事件不允许结算移动。",
        )

    async def start_exploration(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.exploration.start_exploration(context),
            write_message="当前事件不允许开始探索。",
        )

    async def settle_exploration(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.exploration.settle_exploration(context),
            write_message="当前事件不允许结算探索。",
        )

    async def cancel_exploration(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.exploration.cancel_exploration(context),
            write_message="当前事件不允许取消探索。",
        )

    async def list_bounties(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.adventures.list_bounties(context), require_write=False)

    async def accept_bounty(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.adventures.accept_bounty(context),
            write_message="当前事件不允许接取悬赏。",
        )

    async def claim_bounty(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.adventures.claim_bounty(context),
            write_message="当前事件不允许领取悬赏。",
        )

    async def get_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.mainline.get_status(context),
            require_write=False,
        )

    async def start_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.mainline.start_stage(context),
            write_message="当前事件不允许开始主线。",
        )

    async def claim_mainline_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.mainline.claim_reward(context),
            write_message="当前事件不允许领取主线奖励。",
        )

    async def preview_retreat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.advancement.preview(context), require_write=False)

    async def start_retreat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.advancement.start(context),
            write_message="当前事件不允许开始闭关。",
        )

    async def settle_retreat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.advancement.settle(context),
            write_message="当前事件不允许结算闭关。",
        )

    async def recover_retreat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.advancement.settle(context, recover=True),
            write_message="当前事件不允许恢复闭关。",
        )

    async def lease_residence(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.lease(context),
            write_message="当前事件不允许租住居所。",
        )

    async def get_residence(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.livelihood.get_profile(context), require_write=False)

    async def preview_constitution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.constitution.preview(context), require_write=False)

    async def select_constitution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.constitution.select(context),
            write_message="当前事件不允许选择体质。",
        )

    async def get_constitution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.constitution.profile(context), require_write=False)

    async def reshape_constitution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.constitution.reshape(context),
            write_message="当前事件不允许重塑体质。",
        )

    async def preview_talents(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.talent.preview(context), require_write=False)

    async def get_talent_profile(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.talent.profile(context), require_write=False)

    async def unlock_talent(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.talent.unlock(context),
            write_message="当前事件不允许解锁道脉。",
        )

    async def preview_skills(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.skill.preview(context), require_write=False)

    async def get_skill_profile(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.skill.profile(context), require_write=False)

    async def train_skill(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.skill.train(context),
            write_message="当前事件不允许参悟神通。",
        )

    async def preview_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.equipment.preview_tempering(context), require_write=False)

    async def preview_refinement(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.equipment.preview_refinement(context), require_write=False)

    async def temper_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.equipment.temper(context),
            write_message="当前事件不允许祭炼法器。",
        )

    async def refine_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.equipment.refine(context),
            write_message="当前事件不允许重铸法器。",
        )

    async def claim_daily(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.claim_daily(context),
            write_message="当前事件不允许进行道历问安。",
        )

    async def makeup_daily(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.makeup_daily(context),
            write_message="当前事件不允许补录道历。",
        )

    async def water_spirit_tree(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.water_spirit_tree(context),
            write_message="当前事件不允许培育灵木。",
        )

    async def harvest_spirit_tree(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.harvest_spirit_tree(context),
            write_message="当前事件不允许收获灵木。",
        )

    async def get_seven_day_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.get_seven_day_status(context),
            require_write=False,
        )

    async def claim_seven_day_goal(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.claim_seven_day_goal(context),
            write_message="当前事件不允许领取七日目标奖励。",
        )

    async def get_honor_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.get_honor_status(context),
            require_write=False,
        )

    async def claim_achievement(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.claim_achievement(context),
            write_message="当前事件不允许领取功业奖励。",
        )

    async def equip_title(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.equip_title(context),
            write_message="当前事件不允许更换称号。",
        )

    async def redeem_code(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.redeem_code(context),
            write_message="当前事件不允许兑换密令。",
        )

    async def get_dao_contract_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.get_dao_contract_status(context),
            require_write=False,
        )

    async def activate_dao_contract(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.activate_dao_contract(context),
            write_message="当前事件不允许激活道契。",
        )

    async def claim_dao_contract(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.routine.claim_dao_contract(context),
            write_message="当前事件不允许领取道契权益。",
        )

    async def roll_fate_pool(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.gacha.roll_fate_pool(context),
            write_message="当前事件不允许进行机缘寻宝。",
        )

    async def get_wayfaring_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.wayfaring.get_status(context),
            require_write=False,
        )

    async def start_wayfaring(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.wayfaring.start(context),
            write_message="当前事件不允许开启行卷。",
        )

    async def claim_wayfaring_level(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.wayfaring.claim_level(context),
            write_message="当前事件不允许领取行卷奖励。",
        )
