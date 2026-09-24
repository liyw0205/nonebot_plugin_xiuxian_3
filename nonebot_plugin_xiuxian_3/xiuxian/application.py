"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..contracts import CommandContext, CommandResult, validate_command_identity
from .player.use_cases import PlayerApplication
from .production.use_cases import ProductionApplication
from .progression.use_cases import ProgressionApplication
from .progression.endgame_use_cases import EndgameApplication
from .progression.final_battle_use_cases import FinalBattleApplication
from .progression.breakthrough.use_cases import BreakthroughApplication
from .world.use_cases import WorldApplication
from .exploration.use_cases import ExplorationApplication
from .combat.use_cases import CombatApplication
from .adventures.use_cases import AdventuresApplication
from .adventures.mainline_use_cases import AdventuresMainlineApplication
from .adventures.dao_echoes_use_cases import DaoEchoesApplication
from .advancement.use_cases import AdvancementApplication
from .advancement.constitution_use_cases import ConstitutionApplication
from .advancement.talent_use_cases import TalentApplication
from .advancement.skill_use_cases import SkillApplication
from .advancement.equipment_use_cases import EquipmentApplication
from .livelihood.use_cases import LivelihoodApplication
from .livelihood.route_use_cases import RouteApplication
from .livelihood.service_use_cases import ServiceApplication
from .livelihood.project_use_cases import ProjectApplication
from .social.sect_use_cases import SectApplication
from .social.party_use_cases import PartyApplication
from .social.mentor_use_cases import MentorApplication
from .routine.use_cases import RoutineApplication
from .routine.gacha_use_cases import GachaApplication
from .routine.wayfaring_use_cases import WayfaringApplication
from .economy.use_cases import EconomyApplication
from .events.use_cases import EventsApplication
from .events.season_use_cases import FinalHeavenSeasonApplication
from .specials.arena_use_cases import ArenaApplication
from .specials.team_arena_use_cases import TeamArenaApplication
from .quests.use_cases import QuestApplication
from .repository import SQLitePlayerRepository


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository):
        self.player = PlayerApplication(repository)
        self.progression = ProgressionApplication(repository)
        self.endgame = EndgameApplication(repository)
        self.final_battle = FinalBattleApplication(repository)
        self.breakthrough = BreakthroughApplication(repository)
        self.production = ProductionApplication(repository)
        self.world = WorldApplication(repository)
        self.exploration = ExplorationApplication(repository)
        self.combat = CombatApplication(repository)
        self.adventures = AdventuresApplication(repository)
        self.mainline = AdventuresMainlineApplication(repository)
        self.dao_echoes = DaoEchoesApplication(repository)
        self.advancement = AdvancementApplication(repository)
        self.constitution = ConstitutionApplication(repository)
        self.talent = TalentApplication(repository)
        self.skill = SkillApplication(repository)
        self.equipment = EquipmentApplication(repository)
        self.livelihood = LivelihoodApplication(repository)
        self.route = RouteApplication(repository)
        self.service = ServiceApplication(repository)
        self.project = ProjectApplication(repository)
        self.social = SectApplication(repository)
        self.party = PartyApplication(repository)
        self.mentor = MentorApplication(repository)
        self.routine = RoutineApplication(repository)
        self.gacha = GachaApplication(repository)
        self.wayfaring = WayfaringApplication(repository)
        self.economy = EconomyApplication(repository)
        self.events = EventsApplication(repository)
        self.seasons = FinalHeavenSeasonApplication(repository)
        self.arena = ArenaApplication(repository)
        self.team_arena = TeamArenaApplication(repository)
        self.quests = QuestApplication(repository)

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

    async def begin_dao_union(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.begin_dao_union(context),
            write_message="当前事件不允许执行合道。",
        )

    async def begin_tribulation(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.begin_tribulation(context),
            write_message="当前事件不允许进入渡劫。",
        )

    async def choose_ending(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.choose_ending(context),
            write_message="当前事件不允许选择终局。",
        )

    async def preview_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.preview_final_battle(context),
            require_write=False,
        )

    async def create_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.create(context), write_message="当前事件不允许创建终局战。")

    async def join_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.join(context), write_message="当前事件不允许加入终局战。")

    async def start_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.start(context), write_message="当前事件不允许开始终局战。")

    async def choose_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.choose(context), write_message="当前事件不允许选择终局战分支。")

    async def recover_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.start(context, recover=True), write_message="当前事件不允许恢复终局战。")

    async def cancel_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.cancel(context), write_message="当前事件不允许取消终局战。")

    async def replay_final_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.final_battle.replay(context), require_write=False)

    async def start_tribulation_trial(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.start_trial(context),
            write_message="当前事件不允许开始天劫试炼。",
        )

    async def settle_tribulation_trial(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.endgame.settle_trial(context),
            write_message="当前事件不允许结算天劫试炼。",
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

    async def prepare_nascent_soul(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.prepare_nascent_soul(context),
            write_message="当前事件不允许准备元婴。",
        )

    async def resolve_heart_demon(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.resolve_heart_demon(context),
            write_message="当前事件不允许处理心魔。",
        )

    async def recover_soul_fatigue(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.recover_soul_fatigue(context),
            write_message="当前事件不允许恢复神魂疲劳。",
        )

    async def choose_domain(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.choose_domain(context),
            write_message="当前事件不允许选择领域。",
        )

    async def confirm_domain(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.confirm_domain(context),
            write_message="当前事件不允许确认领域。",
        )

    async def cancel_domain(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.cancel_domain(context),
            write_message="当前事件不允许取消领域选择。",
        )

    async def recover_domain_crack(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.breakthrough.recover_domain_crack(context),
            write_message="当前事件不允许恢复领域裂痕。",
        )

    async def preview_recipe(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.production.preview_recipe(context), require_write=False)

    async def start_production(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.start_production(context),
            write_message="当前事件不允许锁定生产资产。",
        )

    async def start_endgame_recipe(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.start_endgame_recipe(context),
            write_message="当前事件不允许开始终局配方。",
        )

    async def settle_endgame_recipe(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.settle_endgame_recipe(context),
            write_message="当前事件不允许结算终局配方。",
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

    async def enter_void_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.world.enter_void_route(context), write_message="当前事件不允许进入虚空航道。")

    async def settle_void_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.world.settle_void_route(context), write_message="当前事件不允许结算虚空航道。")

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

    async def start_training_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.combat.start_training_battle(context),
            write_message="当前事件不允许开始训练战。",
        )

    async def claim_battle_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.combat.claim_battle_reward(context),
            write_message="当前事件不允许领取战斗奖励。",
        )

    async def replay_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.combat.replay_battle(context),
            require_write=False,
        )

    async def get_advanced_quests(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.get_advanced_quests(context), require_write=False)

    async def complete_domain_material_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.complete_domain_material_commission(context), write_message="当前事件不允许完成领域委托。")

    async def complete_ancient_domain_line(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.complete_ancient_domain_line(context), write_message="当前事件不允许推进远古洞天任务。")

    async def start_cross_realm_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.start_cross_realm_battle(context), write_message="当前事件不允许开始跨界战。")

    async def start_void_wall_trial(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.start_void_wall_trial(context), write_message="当前事件不允许开始界壁试炼。")

    async def acquire_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.acquire_void_archive(context), write_message="当前事件不允许探索档案遗迹。")

    async def deliver_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.deliver_void_archive(context), write_message="当前事件不允许交付虚空档案。")

    async def claim_soul_transformation_quest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_soul_transformation(context), write_message="当前事件不允许领取化神许可。")

    async def claim_void_refining_quest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_void_refining(context), write_message="当前事件不允许领取炼虚许可。")

    async def record_dao_union_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.record_dao_union_mainline(context), write_message="当前事件不允许记录合道主线资格。")

    async def start_dao_union_challenge(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.start_dao_union_challenge(context), write_message="当前事件不允许开始合道挑战。")

    async def deliver_dao_union_work(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.deliver_dao_union_work(context), write_message="当前事件不允许交付合道作品。")

    async def claim_dao_union_quest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_dao_union_quest(context), write_message="当前事件不允许领取合道许可。")

    async def complete_dao_origin_task(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.complete_dao_origin_task(context), write_message="当前事件不允许完成道源任务。")

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

    async def get_dao_echoes_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.dao_echoes.get_status(context), require_write=False)

    async def start_dao_echoes_stage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_echoes.start_stage(context),
            write_message="当前事件不允许开始道源主线。",
        )

    async def claim_dao_echoes_stage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_echoes.claim_reward(context),
            write_message="当前事件不允许领取道源主线奖励。",
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

    async def plant_field(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.plant(context),
            write_message="当前事件不允许播种灵田。",
        )

    async def maintain_field(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.maintain(context),
            write_message="当前事件不允许维护灵田。",
        )

    async def harvest_field(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.harvest(context),
            write_message="当前事件不允许收获灵田。",
        )

    async def get_field_profile(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.livelihood.get_plot_profile(context), require_write=False)

    async def list_commissions(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.livelihood.list_commissions(context), require_write=False)

    async def accept_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.accept_commission(context),
            write_message="当前事件不允许接取城镇委托。",
        )

    async def deliver_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.deliver_commission(context),
            write_message="当前事件不允许交付城镇委托。",
        )

    async def list_projects(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.project.list_projects(context), require_write=False)

    async def contribute_project(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.project.contribute(context),
            write_message="当前事件不允许贡献公共项目。",
        )

    async def settle_project(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.project.settle(context),
            write_message="当前事件不允许结算公共项目。",
        )

    async def publish_service(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.service.publish_service(context),
            write_message="当前事件不允许发布服务订单。",
        )

    async def preview_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.route.preview_route(context), require_write=False)

    async def start_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.route.start_route(context),
            write_message="当前事件不允许锁定运输货物。",
        )

    async def settle_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.route.settle_route(context),
            write_message="当前事件不允许结算运输路线。",
        )

    async def create_sect(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.social.create_sect(context),
            write_message="当前事件不允许创建宗门。",
        )

    async def apply_sect(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.social.apply_sect(context),
            write_message="当前事件不允许申请加入宗门。",
        )

    async def list_sect_applications(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.list_applications(context), require_write=False)

    async def review_sect_application(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.social.review_application(context),
            write_message="当前事件不允许审批宗门申请。",
        )

    async def leave_sect(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.social.leave_sect(context),
            write_message="当前事件不允许离开宗门。",
        )

    async def get_sect_profile(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.get_profile(context), require_write=False)

    async def create_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_party(context), write_message="当前事件不允许创建队伍。")

    async def invite_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.invite_party(context), write_message="当前事件不允许邀请队伍成员。")

    async def accept_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.accept_party(context), write_message="当前事件不允许接受队伍邀请。")

    async def reject_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.reject_party(context), write_message="当前事件不允许处理队伍邀请。")

    async def confirm_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.confirm_party(context), write_message="当前事件不允许确认队伍。")

    async def start_party_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.start_party_battle(context), write_message="当前事件不允许发起队伍战斗。")

    async def settle_party_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.settle_party_battle(context), write_message="当前事件不允许结算队伍战斗。")

    async def replay_party_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.replay_party_battle(context), require_write=False)

    async def leave_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.leave_party(context), write_message="当前事件不允许退出队伍。")

    async def get_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.get_party(context), require_write=False)

    async def invite_mentor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.mentor.invite_mentor(context), write_message="当前事件不允许发出拜师邀请。")

    async def accept_mentor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.mentor.accept_mentor(context), write_message="当前事件不允许接受拜师邀请。")

    async def reject_mentor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.mentor.reject_mentor(context), write_message="当前事件不允许拒绝拜师邀请。")

    async def graduate_apprentice(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.mentor.graduate_apprentice(context), write_message="当前事件不允许办理师徒毕业。")

    async def accept_service(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.service.accept_service(context),
            write_message="当前事件不允许承接服务订单。",
        )

    async def cancel_service(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.service.cancel_service(context),
            write_message="当前事件不允许取消服务订单。",
        )

    async def settle_service(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.service.settle_service(context),
            write_message="当前事件不允许结算服务订单。",
        )

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

    async def create_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.create_market_order(context), write_message="当前事件不允许发布摆摊。")

    async def buy_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.buy_market_order(context), write_message="当前事件不允许购买摆摊。")

    async def cancel_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.cancel_market_order(context), write_message="当前事件不允许取消摆摊。")

    async def expire_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.expire_market_order(context), write_message="当前事件不允许清理摆摊。")

    async def list_market_orders(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.list_market_orders(context), require_write=False)

    async def get_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_spirit_spring_event(context), require_write=False)

    async def claim_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.events.claim_spirit_spring_event(context),
            write_message="当前事件不允许领取灵泉事件奖励。",
        )

    async def get_final_heaven_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.seasons.get_final_heaven_season(context),
            require_write=False,
        )

    async def claim_final_heaven_rewards(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.seasons.claim_final_heaven_rewards(context),
            write_message="当前事件不允许领取终局赛季奖励。",
        )

    async def publish_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.publish_snapshot(context),
            write_message="当前事件不允许发布竞技场防守快照。",
        )

    async def revoke_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.revoke_snapshot(context),
            write_message="当前事件不允许撤销竞技场防守快照。",
        )

    async def list_arena_snapshots(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.arena.list_snapshots(context), require_write=False)

    async def challenge_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.challenge(context),
            write_message="当前事件不允许发起竞技场挑战。",
        )

    async def rank_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.rank(context),
            write_message="当前事件不允许发起竞技场排位。",
        )

    async def practice_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.practice(context),
            write_message="当前事件不允许进行竞技场练习。",
        )

    async def grant_arena_practice_consent(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.grant_practice_consent(context),
            write_message="当前事件不允许授权竞技场练习。",
        )

    async def replay_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.arena.replay(context), require_write=False)

    async def claim_arena_result(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.claim_result(context),
            write_message="当前事件不允许确认竞技场结果。",
        )

    async def publish_team_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.team_arena.publish_snapshot(context),
            write_message="当前事件不允许发布组队竞技场快照。",
        )

    async def list_team_arena_snapshots(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.team_arena.list_snapshots(context), require_write=False)

    async def challenge_team_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.team_arena.challenge(context),
            write_message="当前事件不允许发起组队竞技场挑战。",
        )

    async def replay_team_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.team_arena.replay(context), require_write=False)

    async def create_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.create_production_commission(context), write_message="当前事件不允许发布生产委托。")

    async def list_production_commissions(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.list_production_commissions(context), require_write=False)

    async def accept_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.accept_production_commission(context), write_message="当前事件不允许接取生产委托。")

    async def deliver_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.deliver_production_commission(context), write_message="当前事件不允许交付生产委托。")

    async def settle_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.settle_production_commission(context), write_message="当前事件不允许确认生产委托。")

    async def cancel_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.cancel_production_commission(context), write_message="当前事件不允许取消生产委托。")

    async def expire_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.expire_production_commission(context), write_message="当前事件不允许清理生产委托。")

    async def recover_production_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.recover_production_commission(context), write_message="当前事件不允许恢复生产委托。")
