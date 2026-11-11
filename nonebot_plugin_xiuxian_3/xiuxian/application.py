"""Application composition root for feature-specific use-case services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..contracts import CommandContext, CommandResult, validate_command_identity
from .content import ContentBundle, bundled_content
from .player.use_cases import PlayerApplication
from .production.use_cases import ProductionApplication
from .production.facility_use_cases import FacilityApplication
from .items.use_cases import ItemApplication
from .progression.use_cases import ProgressionApplication
from .progression.endgame_use_cases import EndgameApplication
from .progression.final_battle_use_cases import FinalBattleApplication
from .progression.breakthrough.use_cases import BreakthroughApplication
from .world.use_cases import WorldApplication
from .exploration.use_cases import ExplorationApplication
from .combat.use_cases import CombatApplication
from .adventures.use_cases import AdventuresApplication
from .adventures.mainline_use_cases import AdventuresMainlineApplication
from .adventures.mainline import (
    CODEX_ECHOES_STORY_KEY,
    CLOUD_MINE_ECHOES_STORY_KEY,
    CLOUD_CITY_ECHOES_STORY_KEY,
    DAO_SETTLEMENT_STORY_KEY,
    DOMAIN_FRONTIER_STORY_KEY,
    VOID_ARCHIVE_STORY_KEY,
)
from .adventures.dao_echoes_use_cases import DaoEchoesApplication
from .adventures.three_realms_use_cases import ThreeRealmsApplication
from .adventures.secret_realm_use_cases import SecretRealmApplication
from .adventures.legacy_manor_use_cases import LegacyManorApplication
from .advancement.use_cases import AdvancementApplication
from .advancement.constitution_use_cases import ConstitutionApplication
from .advancement.talent_use_cases import TalentApplication
from .advancement.reset_use_cases import TalentResetApplication
from .advancement.skill_use_cases import SkillApplication
from .advancement.equipment_use_cases import EquipmentApplication
from .stats.use_cases import StatsApplication
from .companions.use_cases import CompanionApplication
from .livelihood.use_cases import LivelihoodApplication
from .livelihood.route_use_cases import RouteApplication
from .livelihood.service_use_cases import ServiceApplication
from .livelihood.project_use_cases import ProjectApplication
from .social.sect_use_cases import SectApplication
from .social.party_use_cases import PartyApplication
from .social.mentor_use_cases import MentorApplication
from .social.partner_use_cases import PartnerApplication
from .social.sect_war_use_cases import SectWarApplication
from .social.sect_war_cross_server_use_cases import SectWarCrossServerApplication
from .social.sect_beacon_use_cases import SectBeaconApplication
from .social.sect_alliance_use_cases import SectAllianceApplication
from .social.sect_social_recovery_use_cases import SectSocialRecoveryApplication
from .social.spar_use_cases import SparApplication
from .routine.use_cases import RoutineApplication
from .routine.gacha_use_cases import GachaApplication
from .routine.wayfaring_use_cases import WayfaringApplication
from .economy.use_cases import EconomyApplication
from .economy.cross_realm_trade_use_cases import CrossRealmTradeApplication
from .economy.void_market_use_cases import VoidMarketApplication
from .device.entity_use_cases import DeviceApplication
from .paths.switch_use_cases import PathSwitchApplication
from .paths.rebuild_use_cases import PathRebuildApplication
from .paths.subprofession_switch_use_cases import SubprofessionSwitchApplication
from .social.dao_hall_use_cases import DaoHallApplication
from .social.dao_route_use_cases import DaoRouteApplication
from .events.ascension_day_use_cases import AscensionDayApplication
from .social.partner_task_use_cases import PartnerTaskApplication
from .economy.void_material_use_cases import VoidMaterialApplication
from .economy.auction_use_cases import AuctionApplication
from .economy.purchase_order_use_cases import PurchaseOrderApplication
from .events.use_cases import EventsApplication
from .events.season_use_cases import FinalHeavenSeasonApplication
from .events.three_realms_use_cases import ThreeRealmsSeasonApplication
from .events.domain_front_use_cases import DomainFrontApplication
from .events.void_archive_use_cases import VoidArchiveApplication
from .events.void_frontier_use_cases import VoidFrontierApplication
from .specials.arena_use_cases import ArenaApplication
from .specials.team_arena_use_cases import TeamArenaApplication
from .specials.idle_use_cases import IdleApplication
from .specials.dispatch_use_cases import DispatchApplication
from .specials.codex_use_cases import CodexApplication
from .specials.tower_use_cases import TowerApplication
from .specials.void_spire_use_cases import VoidSpireApplication
from .specials.three_realms_tower_use_cases import ThreeRealmsTowerApplication
from .specials.three_realms_tower_duo_use_cases import ThreeRealmsTowerDuoApplication
from .specials.final_arena_use_cases import FinalArenaApplication
from .specials.story_use_cases import StoryApplication
from .quests.use_cases import QuestApplication
from .repository import SQLitePlayerRepository
from .utils.text import command_link

_HELP_OVERVIEW = (
    "**修仙指南**\n\n"
    "从一介凡人起步，选定道途，再按自己的节奏修行。想做什么，就从相应篇章读起。\n\n"
    f"- {command_link('启程', '修仙帮助 启程')}：登记道号、寻仙与凡人引导。\n"
    f"- {command_link('修炼', '修仙帮助 修炼')}：道途、功法、修为与境界突破。\n"
    f"- {command_link('探索', '修仙帮助 探索')}：行走各地、秘境与主线见闻。\n"
    f"- {command_link('悬赏', '修仙帮助 悬赏')}：接取委托、完成目标与领取酬劳。\n"
    f"- {command_link('生活', '修仙帮助 生活')}：生产、灵田、灵兽与日常收支。\n"
    f"- {command_link('社交', '修仙帮助 社交')}：宗门、道侣与道友切磋。"
)
_HELP_PAGES = {
    "启程": (
        "**启程**\n\n"
        f"尚未登记时，先{command_link('开始修仙', '开始修仙')}；可在指令后写下不超过七字的道号。"
        f"随后{command_link('寻仙问道', '寻仙问道')}，领取启程物资并了解自己的资质。\n\n"
        f"凡人引导从{command_link('完成引导 阅读', '完成引导 阅读')}开始；"
        f"再{command_link('前往近郊', '前往近郊')}，完成采集和一项生产教学。\n\n"
        f"{command_link('我的状态', '我的状态')}可查看境界、所在地与引导进度。"
        f"想换道号时用{command_link('修仙改名', '修仙改名')}，再填新名字；首次取名无需改名卡。"
    ),
    "修炼": (
        "**修炼**\n\n"
        f"完成三项凡人引导后，用{command_link('选择道途', '选择道途')}填写自己的修行方向。"
        "辅修需同时写明炼丹、炼器、布阵、采矿或烹饪。\n\n"
        f"平日以{command_link('开始修炼', '开始修炼')}积累修为，到时{command_link('结算修炼', '结算修炼')}。"
        f"修为足够后{command_link('晋升境界', '晋升境界')}，逐层向前。\n\n"
        f"跨越大境界前，先用{command_link('突破预览', '突破预览')}填写目标境界查看所需准备，"
        f"再用{command_link('开始突破', '开始突破')}填写同一目标。"
    ),
    "探索": (
        "**探索**\n\n"
        f"用{command_link('我的状态', '我的状态')}确认所在地，"
        f"再{command_link('开始探索', '开始探索')}；途中所得在{command_link('结算探索', '结算探索')}时领取。\n\n"
        f"想深入秘境，可先{command_link('秘境预览', '秘境预览')}，"
        f"再用{command_link('进入秘境', '进入秘境')}填写秘境名。"
        f"{command_link('主线道途', '主线道途')}与{command_link('引路簿', '引路簿')}会记录你的见闻与嘉奖。\n\n"
        "云铁矿区需达到筑基；采矿辅修、矿镐或登记许可均可作为准入凭据。"
        f"准备矿镐或许可前，可{command_link('生产预览 基础矿镐', '生产预览 基础矿镐')}"
        f"或{command_link('生产预览 矿区登记', '生产预览 矿区登记')}查看材料。"
        "\n\n云城巡夜需金丹一层且身在云城；按现有日限完成真实遭遇战后才会结算胜场。"
        f"可先{command_link('开始探索 云城巡夜', '开始探索 云城巡夜')}，再{command_link('结算探索', '结算探索')}领取结果。"
        "\n\n守界终关之后，可从领域前线主线的归镇筹粮开始避难所后记：返镇、实际贡献，再完整交班。"
        f"{command_link('领域前线主线', '领域前线主线')}会记下已解锁的关卡。"
        "\n\n虚空档案归乡后，补给回响会开放第一航道：先"
        f"{command_link('前往 虚空第一航道', '前往 虚空第一航道')}，再用"
        f"{command_link('开始探索 虚空航道历练', '开始探索 虚空航道历练')}取得已结算的航道所得。"
        "\n\n寻道期的图鉴回响从玄天近郊开始：先"
        f"{command_link('图鉴回响主线', '图鉴回响主线')}查看关卡，"
        f"再{command_link('开始图鉴回响主线 近郊寻迹', '开始图鉴回响主线 近郊寻迹')}沿公开山路抵达近郊；"
        "近郊历练与雾隐洞天秘境的真实结算会补全两页图鉴。"
    ),
    "悬赏": (
        "**悬赏**\n\n"
        f"先看{command_link('悬赏榜', '悬赏榜')}，挑选自己能完成的委托。榜上会列出准入、目标、进度与奖励范围。\n\n"
        f"用{command_link('接取悬赏 悬赏名', '接取悬赏')}填入选定的委托名；"
        "不写名字则随机选择当前可接的一桩。"
        f"达标后{command_link('领取悬赏', '领取悬赏')}，领回酬劳。\n\n"
        "每条悬赏按 UTC 自然日分别计次，同一时间只能承接一桩。"
        "接取时确定本次目标和奖励，需在有效期内完成并领取。"
    ),
    "生活": (
        "**生活**\n\n"
        f"制作前先用{command_link('生产预览', '生产预览')}填写配方名，核对材料与花费；"
        f"备妥后{command_link('开始生产', '开始生产')}填写同一配方，到时{command_link('领取生产', '领取生产')}。\n\n"
        f"{command_link('我的灵田', '我的灵田')}可查看田间生长，成熟后{command_link('灵田收获', '灵田收获')}。"
        f"居所内可{command_link('休整', '休整')}恢复体力与精力，结束后{command_link('结算休整', '结算休整')}。"
        f"物资可{command_link('存入居所', '存入居所')}、{command_link('取回居所', '取回居所')}，"
        f"用{command_link('我的物资箱', '我的物资箱')}查看格数与存量。\n\n"
        f"想托人跑腿，可{command_link('派遣预览', '派遣预览')}查看各境界差事；"
        f"选定后{command_link('接受派遣', '接受派遣')}填写任务名，到期再{command_link('结算派遣', '结算派遣')}。\n\n"
        f"想离线安排，可{command_link('挂机预览', '挂机预览')}查看闲居路线；"
        f"选定后{command_link('开始挂机', '开始挂机')}填写路线名，到时可{command_link('领取挂机', '领取挂机')}，"
        f"开始后六十秒内还能{command_link('取消挂机', '取消挂机')}。\n\n"
        f"{command_link('公共项目', '公共项目')}可查看本周建设；完成运输后，用"
        f"{command_link('贡献公共项目 项目名 运输', '贡献公共项目')}填入项目名，贡献本人尚未记过的运输。"
        "领域避难所个人贡献满十点后，可安排十小时的避难所看守；完整领取才完成灯火长守后记。\n\n"
        f"护祖终关后，{command_link('领域前线主线', '领域前线主线')}中的“重巡万兽山”可开启祖灵栖地后记。"
        f"完成妖界引导并备妥 80 点妖界声望、500 灵石后，"
        f"{command_link('申请贸易许可 妖界', '申请贸易许可 妖界')}可取得七日许可；"
        f"再{command_link('开始挂机 妖界栖地', '开始挂机 妖界栖地')}，八小时后完整领取灵米与灵叶。"
        "护祖权限之外，祖灵栖地项目仍要求 300 点妖界声望；先用公共项目查看本周状态，再贡献本人新取得的物资。\n\n"
        "虚空档案归乡后的补给回响需要炼虚一层：在第一航道完成主线抵达后，"
        f"可用{command_link('挂机预览 虚空补给看守', '挂机预览 虚空补给看守')}查看十二小时完整窗口，"
        f"再{command_link('开始挂机 虚空补给看守', '开始挂机 虚空补给看守')}；完整领取才计入主线，逾时保底不替代交接。\n\n"
        "道源门抵达道统服务处后，可用"
        f"{command_link('道统余响主线', '道统余响主线')}查看公开轮值后记；"
        f"先{command_link('开始道统余响主线 抵达服务处', '开始道统余响主线 抵达服务处')}，"
        "再按关卡指引完整领取道统据点看守，并成功结算道统服务派遣；"
        "只认本关开始后的本人记录，失败或逾时可按既有日限重试。\n\n"
        "图鉴回响两页记录完成后，寻道期可按既有门槛使用观兽与塔外守望：先"
        f"{command_link('挂机预览 观兽', '挂机预览 观兽')}和{command_link('挂机预览 塔外守望', '挂机预览 塔外守望')}确认门槛，"
        "两条路线都要在主线开始后完整领取，逾时保底不替代主线交班。\n\n"
        "筑基四层后可接云铁守望回响：先"
        f"{command_link('云铁守望回响主线', '云铁守望回响主线')}查看关卡，"
        f"再{command_link('开始云铁守望回响主线 矿口听风', '开始云铁守望回响主线 矿口听风')}沿公开山道抵达云铁矿区；"
        "之后按关卡提示结算云铁矿区采掘，并在本关开始后完整领取矿区看守。逾时保底不替代主线交接。\n\n"
        "金丹一层后可接云城店铺回响：先"
        f"{command_link('云城店铺回响主线', '云城店铺回响主线')}查看关卡，"
        f"再{command_link('开始云城店铺回响主线 云城听更', '开始云城店铺回响主线 云城听更')}沿公开路线抵达云城；"
        "随后按关卡提示完成云城巡夜真实胜场，并在云城地方名望达到 200 后完整领取店铺闲居。逾时保底不替代主线交班。\n\n"
        f"{command_link('每日修行', '每日修行')}记下日常安排，"
        f"{command_link('道历问安', '道历问安')}领取当日问安所得。\n\n"
        f"{command_link('灵兽状态', '灵兽状态')}可查看同行灵兽与灵骑；"
        f"{command_link('灵兽相伴', '灵兽相伴')}填写灵兽名或编号可与它静处，每日一次，御兽体质另有加成。"
        f"行囊和鞍具可先查{command_link('生产预览 小型灵兽行囊', '生产预览 小型灵兽行囊')}"
        f"或{command_link('生产预览 竹鹿鞍具', '生产预览 竹鹿鞍具')}；"
        f"制成后用{command_link('装备灵具', '装备灵具')}填写灵兽号与灵具名。\n\n"
        f"买卖所需物资时，先看{command_link('摆摊列表', '摆摊列表')}了解货物与标价。"
    ),
    "社交": (
        "**社交**\n\n"
        f"{command_link('我的宗门', '我的宗门')}可查看归属。想自立门户，用{command_link('创建宗门', '创建宗门')}填写名称；"
        f"想拜入已有宗门，用{command_link('申请入宗', '申请入宗')}填写宗门号或名称。\n\n"
        f"掌门可用{command_link('审批入宗', '审批入宗')}填写申请号与同意或拒绝，处理入宗申请。\n\n"
        f"与道友结伴，可用{command_link('邀请结为道侣', '邀请结为道侣')}填写对方道号；"
        f"想交流身手，用{command_link('切磋', '切磋')}填写对方道号。\n\n"
        f"竞技场按周结算：先{command_link('竞技场赛季', '竞技场赛季')}查看本周名次与段位，\n"
        f"周榜结束后用{command_link('领取竞技场赛季奖励', '领取竞技场赛季奖励')}按冻结名次领取；对战本身不转移资产。\n\n"
        f"宗门立稳后，可用{command_link('道统', '道统')}查看三条路线；"
        f"合道议事时{command_link('道统投票', '道统投票')}填写路线名，届时{command_link('道统结算', '道统结算')}定线。"
        f"留界宗门可{command_link('建立据点', '建立据点')}，再用{command_link('据点', '据点')}查看已建项目与建设进度。"
    ),
}


class XiuxianApplication:
    """Expose feature services to adapters without mixing feature rules."""

    def __init__(self, repository: SQLitePlayerRepository, content: ContentBundle | None = None):
        self.content = content
        self.player = PlayerApplication(repository, content)
        self.progression = ProgressionApplication(repository)
        self.endgame = EndgameApplication(repository)
        self.final_battle = FinalBattleApplication(repository)
        self.breakthrough = BreakthroughApplication(repository)
        self.production = ProductionApplication(repository)
        self.facilities = FacilityApplication(repository)
        self.items = ItemApplication(repository)
        self.world = WorldApplication(repository)
        self.exploration = ExplorationApplication(repository)
        self.combat = CombatApplication(repository)
        self.adventures = AdventuresApplication(repository)
        self.mainline = AdventuresMainlineApplication(repository)
        self.domain_frontier_mainline = AdventuresMainlineApplication(
            repository,
            story_key=DOMAIN_FRONTIER_STORY_KEY,
            title="领域前线主线",
            start_command="开始领域前线主线",
            claim_command="领取领域前线主线奖励",
        )
        self.void_archive_mainline = AdventuresMainlineApplication(
            repository,
            story_key=VOID_ARCHIVE_STORY_KEY,
            title="虚空档案主线",
            start_command="开始虚空档案主线",
            claim_command="领取虚空档案主线奖励",
        )
        self.dao_settlement_mainline = AdventuresMainlineApplication(
            repository,
            story_key=DAO_SETTLEMENT_STORY_KEY,
            title="道统余响主线",
            start_command="开始道统余响主线",
            claim_command="领取道统余响主线奖励",
        )
        self.codex_echoes_mainline = AdventuresMainlineApplication(
            repository,
            story_key=CODEX_ECHOES_STORY_KEY,
            title="图鉴回响主线",
            start_command="开始图鉴回响主线",
            claim_command="领取图鉴回响主线奖励",
        )
        self.cloud_mine_echoes_mainline = AdventuresMainlineApplication(
            repository,
            story_key=CLOUD_MINE_ECHOES_STORY_KEY,
            title="云铁守望回响主线",
            start_command="开始云铁守望回响主线",
            claim_command="领取云铁守望回响主线奖励",
        )
        self.cloud_city_echoes_mainline = AdventuresMainlineApplication(
            repository,
            story_key=CLOUD_CITY_ECHOES_STORY_KEY,
            title="云城店铺回响主线",
            start_command="开始云城店铺回响主线",
            claim_command="领取云城店铺回响主线奖励",
        )
        self.dao_echoes = DaoEchoesApplication(repository)
        self.three_realms = ThreeRealmsApplication(repository)
        self.secret_realms = SecretRealmApplication(repository)
        self.legacy_manor = LegacyManorApplication(repository)
        self.abyss_echo_manor = LegacyManorApplication(
            repository,
            instance_key="instance.legacy.demon_abyss_echo",
            display_name="残响遗府",
            enter_command="进入残响遗府",
            status_command="残响遗府状态",
            choose_command="选择残响遗府节点",
            settle_command="结算残响遗府",
        )
        self.advancement = AdvancementApplication(repository)
        self.constitution = ConstitutionApplication(repository)
        self.talent = TalentApplication(repository)
        self.talent_reset = TalentResetApplication(repository)
        self.skill = SkillApplication(repository)
        self.equipment = EquipmentApplication(repository)
        self.stats = StatsApplication(repository)
        self.companions = CompanionApplication(repository)
        self.livelihood = LivelihoodApplication(repository)
        self.route = RouteApplication(repository)
        self.service = ServiceApplication(repository)
        self.project = ProjectApplication(repository)
        self.social = SectApplication(repository)
        self.party = PartyApplication(repository)
        self.mentor = MentorApplication(repository)
        self.partner = PartnerApplication(repository)
        self.sect_war = SectWarApplication(repository)
        self.cross_server_sect_war = SectWarCrossServerApplication(repository)
        self.sect_beacon = SectBeaconApplication(repository)
        self.sect_alliance = SectAllianceApplication(repository)
        self.sect_social_recovery = SectSocialRecoveryApplication(repository)
        self.spar = SparApplication(repository)
        self.routine = RoutineApplication(repository)
        self.gacha = GachaApplication(repository)
        self.wayfaring = WayfaringApplication(repository)
        self.economy = EconomyApplication(repository)
        self.cross_realm_trade = CrossRealmTradeApplication(repository)
        self.void_market = VoidMarketApplication(repository)
        self.device = DeviceApplication(repository)
        self.path_switch = PathSwitchApplication(repository)
        self.path_rebuild = PathRebuildApplication(repository)
        self.subprofession_switch = SubprofessionSwitchApplication(repository)
        self.dao_hall = DaoHallApplication(repository)
        self.dao_route = DaoRouteApplication(repository)
        self.ascension_day = AscensionDayApplication(repository)
        self.partner_task = PartnerTaskApplication(repository)
        self.void_material = VoidMaterialApplication(repository)
        self.auction = AuctionApplication(repository)
        self.purchase_orders = PurchaseOrderApplication(repository)
        self.purchase = self.purchase_orders
        self.events = EventsApplication(repository)
        self.seasons = FinalHeavenSeasonApplication(repository)
        self.three_realms_seasons = ThreeRealmsSeasonApplication(repository)
        self.domain_front = DomainFrontApplication(repository, self.combat)
        self.void_archive = VoidArchiveApplication(repository)
        self.void_frontier = VoidFrontierApplication(repository)
        self.arena = ArenaApplication(repository)
        self.team_arena = TeamArenaApplication(repository)
        self.idle = IdleApplication(repository)
        self.dispatch = DispatchApplication(repository)
        self.codex = CodexApplication(repository)
        self.tower = TowerApplication(repository)
        self.void_spire = VoidSpireApplication(repository)
        self.three_realms_tower = ThreeRealmsTowerApplication(repository)
        self.three_realms_tower_duo = ThreeRealmsTowerDuoApplication(repository)
        self.final_arena = FinalArenaApplication(repository)
        self.story = StoryApplication(repository)
        self.quests = QuestApplication(repository)

    async def get_help(self, context: CommandContext) -> CommandResult:
        if not context.command_args:
            return CommandResult(True, "HELP_OVERVIEW", _HELP_OVERVIEW, context.request_id)
        if len(context.command_args) == 1 and context.command_args[0] in _HELP_PAGES:
            category = context.command_args[0]
            body = _HELP_PAGES[category]
            if category == "探索":
                body += "\n\n" + self._exploration_mode_lines()
                secret_lines = self._secret_realm_help_lines()
                if secret_lines:
                    body += "\n\n" + secret_lines
                arena_lines = self._final_arena_help_lines()
                if arena_lines:
                    body += "\n\n" + arena_lines
                ascension_lines = self._ascension_day_help_lines()
                if ascension_lines:
                    body += "\n\n" + ascension_lines
            elif category == "修炼":
                path_lines = self._path_switch_help_lines()
                if path_lines:
                    body += "\n\n" + path_lines
                reset_lines = self._talent_reset_help_lines()
                if reset_lines:
                    body += "\n\n" + reset_lines
                rebuild_lines = self._path_rebuild_help_lines()
                if rebuild_lines:
                    body += "\n\n" + rebuild_lines
                switch_lines = self._subprofession_switch_help_lines()
                if switch_lines:
                    body += "\n\n" + switch_lines
            elif category == "生活":
                dispatch_lines = self._dispatch_help_lines()
                if dispatch_lines:
                    body += "\n\n" + dispatch_lines
                market_lines = self._void_market_help_lines()
                if market_lines:
                    body += "\n\n" + market_lines
                device_lines = self._device_help_lines()
                if device_lines:
                    body += "\n\n" + device_lines
                consign_lines = self._void_material_help_lines()
                if consign_lines:
                    body += "\n\n" + consign_lines
            elif category == "社交":
                hall_lines = self._dao_hall_help_lines()
                if hall_lines:
                    body += "\n\n" + hall_lines
                route_lines = self._dao_route_help_lines()
                if route_lines:
                    body += "\n\n" + route_lines
                partner_lines = self._partner_task_help_lines()
                if partner_lines:
                    body += "\n\n" + partner_lines
            return CommandResult(
                True,
                "HELP_CATEGORY",
                body + "\n\n" + command_link("返回修仙指南", "修仙帮助"),
                context.request_id,
                data={"category": category},
            )
        return CommandResult(
            False,
            "HELP_CATEGORY_NOT_FOUND",
            _HELP_OVERVIEW,
            context.request_id,
        )

    def _exploration_mode_lines(self) -> str:
        """List open exploration modes grouped by location for the help page.

        Rendering is best-effort: a content failure must never block the
        help command, so any error falls back to the static page body.
        """

        try:
            from .exploration.rules import exploration_definitions_by_location
            from .player.rules import LOCATION_LABELS

            grouped = exploration_definitions_by_location(self.content)
            if not grouped:
                return ""
            lines: list[str] = ["**当前开放探索**"]
            for location_key in sorted(grouped):
                location_label = LOCATION_LABELS.get(location_key, location_key)
                for definition in grouped[location_key].values():
                    realm_text = (
                        f"{definition.required_realm}·L{definition.required_layer}"
                        if definition.required_realm
                        else "凡人"
                    )
                    lines.append(
                        f"- {definition.label}（{location_label}，{realm_text}，"
                        f"每日{definition.daily_limit}次）"
                    )
            return "\n".join(lines)
        except Exception:
            return ""

    def _dispatch_help_lines(self) -> str:
        """List content-driven mid/high realm dispatches for the life page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .specials.dispatch_rules import dispatch_definitions

            definitions = [
                definition
                for definition in dispatch_definitions(self.content).values()
                if definition.required_realm and definition.required_layer is not None
            ]
            if not definitions:
                return ""
            content = self.content or bundled_content()

            def _rank(definition) -> tuple[int, int, str]:
                realm = content.get("realm", definition.required_realm)
                rank = int(realm.get("rank", 0)) if realm else 0
                return (rank, definition.required_layer or 0, definition.key)

            definitions.sort(key=_rank)
            lines: list[str] = [
                "**中高阶派遣**",
                "> 点选差事名可预填接受指令；接受即冻结风险与奖励。",
            ]
            for definition in definitions:
                realm_key = definition.required_realm or ""
                realm_label = content.label("realm", realm_key)
                lines.append(
                    f"- {command_link(definition.label, f'接受派遣 {definition.label}')}"
                    f"（{realm_label} L{definition.required_layer}，"
                    f"{definition.duration_seconds // 60} 分钟，每日 {definition.daily_limit} 次）"
                )
            return "\n".join(lines)
        except Exception:
            return ""

    def _void_market_help_lines(self) -> str:
        """List the weekly void market offers on the life page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .economy.void_market_rules import void_market_definition

            definition = void_market_definition(self.content)
            if not definition.offers:
                return ""
            lines: list[str] = [
                "**虚空集市**",
                "> 抵达虚空集市后可购买下列物资；每周一 00:00（UTC）换库，"
                "每人每日限购三件。",
            ]
            for offer in definition.offers:
                lines.append(
                    f"- {command_link(offer.label, f'购买虚空物资 {offer.label}')}"
                    f"（灵石 {offer.price_spirit_stones} / 件，每周 {offer.stock} 件）"
                )
            return "\n".join(lines)
        except Exception:
            return ""

    def _partner_task_help_lines(self) -> str:
        """Describe the partner endgame task on the social page."""

        try:
            from .social.partner_task_content import partner_task_defaults

            record = partner_task_defaults(self.content)
            return "\n".join(
                [
                    f"**{record['name']}**",
                    f"> 道侣双方终局未定时可共赴一次协作：助战胜利 "
                    f"{record['target_amount']} 场，各得世界功勋 {record['reward_world_merit']}"
                    "；协作不改任何一方的结局。",
                    f"- {command_link('道侣协作', '道侣协作')}查看进度与领取",
                ]
            )
        except Exception:
            return ""

    def _ascension_day_help_lines(self) -> str:
        """Describe the ascension day on the explore page."""

        try:
            from .events.ascension_day_rules import ascension_day_definition

            definition = ascension_day_definition(self.content)
            return "\n".join(
                [
                    f"**{definition.name}**",
                    f"> 赛季落幕后 {definition.window_hours} 小时内可查看本届结局、三榜与新篇章入口；"
                    "只作展示，不改任何资产。",
                    f"- {command_link('飞升日', '飞升日')}查看结局与新篇章",
                ]
            )
        except Exception:
            return ""

    def _void_material_help_lines(self) -> str:
        """Describe the void-material consignment market on the life page."""

        try:
            from .economy.void_material_content import void_material_defaults

            record = void_material_defaults(self.content)
            admission = record["admission"]
            return "\n".join(
                [
                    f"**{record['name']}**",
                    f"> 炼虚 L{admission['min_layer']} 或 {admission['min_merit']} 虚空功勋可寄售"
                    f"虚空物资：挂单 {record['listing_hours']} 小时，"
                    f"成交手续费 {record['fee_bp'] / 100:.0f}%，到期自动退回。",
                    f"- {command_link('虚空寄售', '虚空寄售')}查看在售物资与规则",
                ]
            )
        except Exception:
            return ""

    def _dao_route_help_lines(self) -> str:
        """Describe the weekly dao-route council on the social page."""

        try:
            from .social.dao_route_rules import dao_route_definition, dao_route_option_list

            definition = dao_route_definition(self.content)
            options = dao_route_option_list(self.content)
            if not options:
                return ""
            names = "、".join(option.name for option in options)
            lines = [
                f"**{definition.name}**",
                f"> 宗门 {definition.required_sect_level} 级以上的合道修士每周可投一票，"
                f"满 {definition.required_voters} 票按多数定线，"
                f"结算耗公共功勋 {definition.required_sect_merit}，锁定 {definition.lock_days} 天。",
                f"- {command_link('道统', '道统')}查看现行路线与本周票数",
                f"- {command_link('道统投票 守界', '道统投票 守界')}投下一票（可选 {names}）",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _dao_hall_help_lines(self) -> str:
        """Describe the dao hall on the social page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .social.dao_hall_rules import dao_hall_definition

            definition = dao_hall_definition(self.content)
            return "\n".join(
                [
                    f"**{definition.name}**",
                    f"> 唯有留界者可开辟据点：世界功勋 {definition.required_world_merit}、"
                    f"灵石 {definition.spirit_stones}（计入库房）。",
                    f"- {command_link('据点', '据点')}查看状态、成员与建设进度",
                    f"- 核心席位 {definition.core_capacity} 人，周维护 "
                    f"{definition.maintenance_spirit_stones} 灵石；被毁后 "
                    f"{definition.rebuild_hours} 小时内维护不收费",
                    f"- {command_link('建设据点 太清殿', '建设据点 太清殿')}以世界功勋扩建核心席位",
                ]
            )
        except Exception:
            return ""

    def _device_help_lines(self) -> str:
        """List the assembler devices on the life page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .device.entity_rules import device_definitions

            definitions = device_definitions(self.content)
            if not definitions:
                return ""
            lines: list[str] = [
                "**机关**",
                "> 器修可组装一件机关随行出战；机关按行动消耗耐久，损坏后需维修。",
            ]
            for definition in definitions.values():
                if definition.status != "active":
                    continue
                lines.append(
                    f"- {command_link(definition.label, f'组装机关 {definition.label}')}"
                    f"（攻击为自身的 {definition.attack_multiplier_bp / 100:.0f}%，"
                    f"持续 {definition.duration_rounds} 回合）"
                )
            if len(lines) == 2:
                return ""
            return "\n".join(lines)
        except Exception:
            return ""

    def _path_switch_help_lines(self) -> str:
        """Describe the first-stage path switch on the cultivation page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .paths.switch_content import path_switch_definition

            definition = path_switch_definition(self.content)
            content = self.content or bundled_content()
            realm = content.label("realm", definition.min_realm)
            cost = f"灵石 {definition.spirit_stone_cost}"
            token = content.label("item", definition.token_item_key)
            lines = [
                "**道途转修**",
                f"> {realm} {definition.min_layer} 层后可重择首要道途；"
                f"需 {cost} 与 {token} ×{definition.token_quantity}。",
                f"- {command_link('领取转修令', '领取转修令')}（每名角色一次）",
                f"- {command_link('转修道途 法修', '转修道途 法修')}（先预览保留、冻结与清理项）",
                f"- {command_link('确认转修', '确认转修')}",
                f"- {command_link('取消转修', '取消转修')}",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _path_rebuild_help_lines(self) -> str:
        """Describe the one-time nascent-soul rebuild on the cultivation page."""

        try:
            from .paths.rebuild_content import path_rebuild_definition

            definition = path_rebuild_definition(self.content)
            content = self.content or bundled_content()
            realm = content.label("realm", definition.min_realm)
            token = content.label("item", definition.token_item_key)
            lines = [
                "**道途重构（元婴）**",
                f"> {realm} {definition.min_layer} 层、三界声望各 1000 且完成三界主线后，"
                f"可消耗灵石 {definition.spirit_stone_cost} 与 {token} 重择首要道途；每角色一次。",
                f"- {command_link('道途重构预览 法修', '道途重构预览 法修')}",
                f"- {command_link('确认道途重构', '确认道途重构')}",
                f"- {command_link('取消道途重构', '取消道途重构')}",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _subprofession_switch_help_lines(self) -> str:
        """Describe the standalone support sub-profession switch."""

        try:
            from .paths.subprofession_switch_content import (
                subprofession_switch_definition,
            )

            definition = subprofession_switch_definition(self.content)
            realm = self.content.label("realm", definition.min_realm)
            lines = [
                "**辅修切换（辅修道途）**",
                f"> {realm} L{definition.min_layer}、灵石 {definition.spirit_stone_cost}，"
                f"可单独改修一门辅修；冷却 7 天，旧熟练度保留。",
                f"- {command_link('辅修预览 炼丹', '辅修预览 炼丹')}",
                f"- {command_link('确认辅修', '确认辅修')}",
                f"- {command_link('取消辅修', '取消辅修')}",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _talent_reset_help_lines(self) -> str:
        """Describe the first-version talent reset on the cultivation page."""

        try:
            from .advancement.reset_content import talent_reset_definition

            definition = talent_reset_definition(self.content)
            content = self.content or bundled_content()
            realm = content.label("realm", definition.min_realm)
            lines = [
                "**道脉重置**",
                f"> {realm} {definition.min_layer} 层后可重置当前道脉；"
                f"消耗灵石 {definition.spirit_stone_cost}，"
                f"返还 {definition.refund_bp // 100}% 已用天赋点。",
                f"- {command_link('道脉重置预览', '道脉重置预览')}",
                f"- {command_link('确认道脉重置', '确认道脉重置')}",
                f"- {command_link('取消道脉重置', '取消道脉重置')}",
            ]
            return "\n".join(lines)
        except Exception:
            return ""

    def _final_arena_help_lines(self) -> str:
        """List the endgame final arena tiers on the explore page.

        Help rendering stays best-effort: content failures fall back to the
        static page body and never block command dispatch.
        """

        try:
            from .specials.final_arena_rules import final_arena_definition

            definition = final_arena_definition(self.content)
            if not definition.tiers:
                return ""
            from .content import bundled_content

            content = self.content or bundled_content()
            realm_label = content.label("realm", definition.required_realm)
            lines: list[str] = [
                "**终局天榜**",
                f"> 活动轮次内开放（每个 UTC 四小时轮次最多 "
                f"{definition.attempt_limit_per_round} 次）；需抵达终局天榜并达到 "
                f"{realm_label} L{definition.required_layer}，榜上名次不影响飞升资格。",
            ]
            for tier in definition.tiers:
                lines.append(
                    f"- {command_link(tier.label, f'挑战天榜 {tier.label}')}"
                    f"（第 {tier.tier_index} 重守榜人，体力 {definition.stamina_cost}）"
                )
            return "\n".join(lines)
        except Exception:
            return ""

    def _secret_realm_help_lines(self) -> str:
        """List active common secret realms with prefill links on the explore page."""

        try:
            from .adventures.secret_realm_rules import secret_realm_definitions

            content = self.content or bundled_content()
            definitions = list(secret_realm_definitions(content).values())
            if not definitions:
                return ""
            lines: list[str] = [
                "**当前开放秘境**",
                "> 点选秘境名可预填进入指令；到达入口并满足境界、体力与凭证后可进入。",
            ]
            for definition in definitions:
                realm_label = content.label("realm", definition.required_realm)
                location_label = content.label("location", definition.location_key)
                period = "日" if definition.quota_period == "day" else "周"
                lines.append(
                    f"- {command_link(definition.label, f'进入秘境 {definition.label}')}"
                    f"（{location_label}，{realm_label} L{definition.required_layer}，"
                    f"体力 {definition.stamina_cost}，每{period} {definition.quota_limit} 次）"
                )
            return "\n".join(lines)
        except Exception:
            return ""

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
        result = await handler()
        if not result.data:
            return result
        return CommandResult(
            ok=result.ok,
            code=result.code,
            message=result.message,
            request_id=result.request_id,
            operation_id=result.operation_id,
            data=result.data,
            retryable=result.retryable,
            actions=result.actions,
        )

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

    async def preview_stats(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.stats.preview(context), require_write=False)

    async def explain_stat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.stats.explain(context), require_write=False)

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

    async def purify_pollution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.production.purify_pollution(context),
            write_message="当前事件不允许净化污染。",
        )

    async def use_item(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.items.use_item(context),
            write_message="当前事件不允许使用物品。",
        )

    async def claim_facility_slot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.facilities.claim_facility_slot(context))

    async def maintain_player_facilities(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.facilities.maintain_player_facilities(context))

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

    async def board_cloud_boat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.board_cloud_boat(context),
            write_message="当前事件不允许乘坐云舟。",
        )

    async def settle_cloud_boat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.settle_cloud_boat(context),
            write_message="当前事件不允许结算云舟。",
        )

    async def recover_cloud_boat(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.recover_cloud_boat(context),
            write_message="当前事件不允许恢复云舟。",
        )

    async def accept_demon_intro(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.accept_demon_intro(context),
            write_message="当前事件不允许确认魔界引导。",
        )

    async def read_beast_history(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.read_beast_history(context),
            write_message="当前事件不允许记录妖界史阅读。",
        )

    async def complete_beast_intro(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.complete_beast_intro(context),
            write_message="当前事件不允许完成妖界引导。",
        )

    async def use_array_hall(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.world.use_array_hall(context),
            write_message="当前事件不允许使用阵堂。",
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

    async def choose_cloud_boat_storm(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.exploration.choose_cloud_boat_storm(context),
            write_message="当前事件不允许处理云舟风暴。",
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
            require_write=False,
            write_message="当前事件不允许开始训练战。",
        )

    async def start_demon_war_front_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.combat.start_demon_war_front_battle(context),
            write_message="当前事件不允许开始魔界战。",
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

    async def get_guidance_quests(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.get_guidance_quests(context), require_write=False)

    async def claim_guidance_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.quests.claim_guidance_reward(context),
            write_message="当前事件不允许领取引路嘉奖。",
        )

    async def get_daily_tasks(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.events.get_daily_tasks(context),
            require_write=False,
        )

    async def claim_daily_task_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.events.claim_daily_task_reward(context),
            write_message="当前状态不允许领取日课嘉奖。",
        )

    async def complete_domain_material_commission(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.complete_domain_material_commission(context), write_message="当前事件不允许完成领域委托。")

    async def complete_ancient_domain_line(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.complete_ancient_domain_line(context), write_message="当前事件不允许推进远古洞天任务。")

    async def start_cross_realm_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.start_cross_realm_battle(context), write_message="当前事件不允许开始跨界战。")

    async def start_void_wall_trial(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.start_void_wall_trial(context), write_message="当前事件不允许开始界壁试炼。")

    async def acquire_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_archive.run_archive(context), write_message="当前事件不允许探索档案遗迹。")

    async def get_void_archive_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_archive.get_status(context), require_write=False)

    async def claim_void_archive_task(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_archive.claim_task(context), write_message="当前事件不允许领取档案碎片任务。")

    async def deliver_void_archive(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.deliver_void_archive(context), write_message="当前事件不允许交付虚空档案。")

    async def get_void_frontier_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_frontier.get_void_frontier_season(context), require_write=False)

    async def claim_void_frontier_weekly(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_frontier.claim_void_frontier_weekly(context), write_message="当前事件不允许领取虚空前线周任务。")

    async def claim_void_frontier_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_frontier.claim_void_frontier_reward(context), write_message="当前事件不允许领取虚空前线赛季奖励。")

    async def claim_soul_transformation_quest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_soul_transformation(context), write_message="当前事件不允许领取化神许可。")

    async def claim_void_refining_quest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_void_refining(context), write_message="当前事件不允许领取炼虚许可。")

    async def claim_demon_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.quests.claim_demon_mainline(context), write_message="当前事件不允许领取魔界主线。")

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
            write_message="此刻无缘踏入这段主线。",
        )

    async def claim_mainline_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.mainline.claim_reward(context),
            write_message="此刻无缘收取这段主线所得。",
        )

    async def get_domain_frontier_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.domain_frontier_mainline.get_status(context),
            require_write=False,
        )

    async def start_domain_frontier_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.domain_frontier_mainline.start_stage(context),
            write_message="此刻无缘踏入领域前线主线。",
        )

    async def claim_domain_frontier_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.domain_frontier_mainline.claim_reward(context),
            write_message="此刻无缘收取领域前线主线所得。",
        )

    async def get_void_archive_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_archive_mainline.get_status(context),
            require_write=False,
        )

    async def start_void_archive_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_archive_mainline.start_stage(context),
            write_message="此刻无缘踏入虚空档案主线。",
        )

    async def claim_void_archive_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_archive_mainline.claim_reward(context),
            write_message="此刻无缘收取虚空档案主线所得。",
        )

    async def get_dao_settlement_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_settlement_mainline.get_status(context),
            require_write=False,
        )

    async def start_dao_settlement_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_settlement_mainline.start_stage(context),
            write_message="此刻无缘踏入道统余响主线。",
        )

    async def claim_dao_settlement_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_settlement_mainline.claim_reward(context),
            write_message="此刻无缘收取道统余响主线所得。",
        )

    async def get_codex_echoes_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.codex_echoes_mainline.get_status(context),
            require_write=False,
        )

    async def start_codex_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.codex_echoes_mainline.start_stage(context),
            write_message="此刻无缘踏入图鉴回响主线。",
        )

    async def claim_codex_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.codex_echoes_mainline.claim_reward(context),
            write_message="此刻无缘收取图鉴回响主线所得。",
        )

    async def get_cloud_mine_echoes_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_mine_echoes_mainline.get_status(context),
            require_write=False,
        )

    async def start_cloud_mine_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_mine_echoes_mainline.start_stage(context),
            write_message="此刻无缘踏入云铁守望回响主线。",
        )

    async def claim_cloud_mine_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_mine_echoes_mainline.claim_reward(context),
            write_message="此刻无缘收取云铁守望回响主线所得。",
        )

    async def get_cloud_city_echoes_mainline_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_city_echoes_mainline.get_status(context),
            require_write=False,
        )

    async def start_cloud_city_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_city_echoes_mainline.start_stage(context),
            write_message="此刻无缘踏入云城店铺回响主线。",
        )

    async def claim_cloud_city_echoes_mainline(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cloud_city_echoes_mainline.claim_reward(context),
            write_message="此刻无缘收取云城店铺回响主线所得。",
        )

    async def preview_final_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.final_arena.preview(context),
            require_write=False,
        )

    async def challenge_final_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.final_arena.challenge(context),
            write_message="当前事件不允许挑战终局天榜。",
        )

    async def settle_final_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.final_arena.settle(context),
            write_message="当前事件不允许结算终局天榜。",
        )

    async def preview_secret_realms(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.secret_realms.preview(context), require_write=False)

    async def enter_secret_realm(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.secret_realms.enter(context),
            write_message="当前事件不允许进入秘境。",
        )

    async def choose_secret_realm_node(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.secret_realms.choose_node(context),
            write_message="当前事件不允许选择秘境节点。",
        )

    async def settle_secret_realm(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.secret_realms.settle(context),
            write_message="当前事件不允许结算秘境。",
        )

    async def enter_legacy_manor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.legacy_manor.enter(context),
            write_message="当前事件不允许进入遗府。",
        )

    async def get_legacy_manor_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.legacy_manor.status(context), require_write=False)

    async def choose_legacy_manor_node(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.legacy_manor.choose_node(context),
            write_message="当前事件不允许选择遗府节点。",
        )

    async def settle_legacy_manor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.legacy_manor.settle(context),
            write_message="当前事件不允许结算遗府。",
        )

    async def enter_abyss_echo_manor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.abyss_echo_manor.enter(context),
            write_message="当前事件不允许进入残响遗府。",
        )

    async def get_abyss_echo_manor_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.abyss_echo_manor.status(context), require_write=False)

    async def choose_abyss_echo_manor_node(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.abyss_echo_manor.choose_node(context),
            write_message="当前事件不允许推进残响遗府。",
        )

    async def settle_abyss_echo_manor(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.abyss_echo_manor.settle(context),
            write_message="当前事件不允许结算残响遗府。",
        )

    async def settle_boundary_rift(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.secret_realms.boundary_rift.settle(context),
            write_message="当前事件不允许结算界隙裂隙秘境。",
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

    async def get_three_realms_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.three_realms.get_status(context), require_write=False)

    async def start_three_realms_stage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms.start_stage(context),
            write_message="当前事件不允许开始三界主线。",
        )

    async def claim_three_realms_stage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms.claim_reward(context),
            write_message="当前事件不允许领取三界主线奖励。",
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

    async def issue_trade_permit(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.issue_trade_permit(context),
            write_message="当前事件不允许申请贸易许可。",
        )

    async def get_residence(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.livelihood.get_profile(context), require_write=False)

    async def rest_residence(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.rest(context),
            write_message="当前事件不允许开始静养。",
        )

    async def settle_residence_rest(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.settle_rest(context),
            write_message="当前事件不允许结算静养。",
        )

    async def deposit_residence_storage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.deposit_storage(context),
            write_message="当前事件不允许存入居所物资。",
        )

    async def withdraw_residence_storage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.livelihood.withdraw_storage(context),
            write_message="当前事件不允许取回居所物资。",
        )

    async def get_residence_storage(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.livelihood.get_storage(context), require_write=False)

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

    async def withdraw_sect_application(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.social.withdraw_application(context),
            write_message="当前事件不允许撤回入宗申请。",
        )

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

    async def get_sect_shop(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.shop(context), require_write=False)

    async def exchange_sect_item(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.exchange_shop(context), write_message="当前事件不允许执行宗门兑换。")

    async def build_sect_daily(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.daily_build(context), write_message="当前事件不允许宗门建设。")

    async def donate_sect_asset(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.donate(context), write_message="当前事件不允许宗门捐献。")

    async def procure_sect_stock(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.social.procure(context), write_message="当前事件不允许宗门补给。")

    async def get_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_war.get(context), require_write=False)

    async def register_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.sect_war.register(context),
            write_message="当前事件不允许报名宗门战。",
        )

    async def contribute_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.sect_war.contribute(context),
            write_message="当前事件不允许贡献宗门战。",
        )

    async def claim_sect_war_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.sect_war.claim(context),
            write_message="当前事件不允许领取宗门战奖励。",
        )

    async def get_void_fortress(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.fortress(context), require_write=False)

    async def build_void_fortress(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.build_fortress(context), write_message="当前事件不允许建造虚空堡垒。")

    async def maintain_void_fortress(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.maintain_fortress(context), write_message="当前事件不允许维护虚空堡垒。")

    async def get_cross_server_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.get(context), require_write=False)

    async def register_cross_server_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.register(context), write_message="当前事件不允许报名跨服宗门战。")

    async def choose_cross_server_sect_war_branch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.choose_branch(context), write_message="当前事件不允许选择战争机关分支。")

    async def contribute_cross_server_sect_war(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.score(context), write_message="当前事件不允许记录跨服宗门战积分。")

    async def claim_cross_server_sect_war_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.claim(context), write_message="当前事件不允许领取跨服宗门战奖励。")

    async def allocate_cross_server_sect_war_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.cross_server_sect_war.allocate(context), write_message="当前事件不允许分配跨服宗门战奖励。")

    async def get_void_beacon(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_beacon.get(context), require_write=False)

    async def build_void_beacon(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_beacon.build(context), write_message="当前事件不允许建造虚空信标。")

    async def maintain_void_beacon(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_beacon.maintain(context), write_message="当前事件不允许维护虚空信标。")

    async def create_sect_alliance(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_alliance.create(context), write_message="当前事件不允许发起生产联盟。")

    async def get_sect_alliance(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_alliance.get(context), require_write=False)

    async def confirm_sect_alliance(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_alliance.confirm(context), write_message="当前事件不允许确认生产联盟。")

    async def end_sect_alliance(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_alliance.end(context), write_message="当前事件不允许解除生产联盟。")

    async def sync_sect_alliance_research(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_alliance.sync_research(context), write_message="当前事件不允许同步联盟配方。")

    async def create_social_recovery_backup(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_social_recovery.create(context), write_message="当前事件不允许创建跨服社交备份。")

    async def verify_social_recovery_backup(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_social_recovery.verify(context), require_write=False)

    async def restore_social_recovery_backup(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.sect_social_recovery.restore(context), write_message="当前事件不允许恢复跨服社交备份。")

    async def create_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_party(context), write_message="当前事件不允许创建队伍。")

    async def create_arena_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_arena_party(context), write_message="当前事件不允许创建竞技队伍。")

    async def create_boundary_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_boundary_party(context), write_message="当前事件不允许创建界隙队伍。")

    async def create_boundary_rift_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_boundary_rift_party(context), write_message="当前事件不允许创建界隙裂隙秘境队伍。")

    async def create_ancient_domain_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_ancient_domain_party(context), write_message="当前事件不允许创建远古洞天秘境队伍。")

    async def create_void_ruins_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_void_ruins_party(context), write_message="当前事件不允许创建虚空遗迹秘境队伍。")

    async def create_time_fort_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_time_fort_party(context), write_message="当前事件不允许创建时序堡垒秘境队伍。")

    async def create_demon_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_demon_party(context), write_message="当前事件不允许创建魔渊队伍。")

    async def create_beast_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_beast_party(context), write_message="当前事件不允许创建万兽队伍。")

    async def create_standard_pve_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_standard_pve_party(context), write_message="当前事件不允许创建多人副本队伍。")

    async def create_three_realms_tower_duo_party(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.party.create_three_realms_tower_duo_party(context), write_message="当前事件不允许创建三界塔双人队伍。")

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

    async def get_mentor_relations(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.mentor.get_mentor_relations(context), require_write=False)

    async def invite_partner(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.invite_partner(context), write_message="当前事件不允许发出结缘之请。")

    async def accept_partner(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.accept_partner(context), write_message="当前事件不允许接受结缘之请。")

    async def reject_partner(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.reject_partner(context), write_message="当前事件不允许拒绝结缘之请。")

    async def get_partner(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.get_partner(context), require_write=False)

    async def request_partner_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.request_dissolution(context), write_message="当前事件不允许申请解除缘契。")

    async def confirm_partner_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.confirm_dissolution(context), write_message="当前事件不允许确认解除缘契。")

    async def reject_partner_dissolution(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.partner.reject_dissolution(context), write_message="当前事件不允许拒绝解除缘契。")

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

    async def preview_talent_reset(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.talent_reset.preview(context),
            write_message="当前事件不允许预览道脉重置。",
        )

    async def confirm_talent_reset(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.talent_reset.confirm(context),
            write_message="当前事件不允许确认道脉重置。",
        )

    async def cancel_talent_reset(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.talent_reset.cancel(context),
            write_message="当前事件不允许取消道脉重置。",
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

    async def list_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.equipment.list_equipment(context), require_write=False)

    async def equip_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.equipment.equip(context),
            write_message="当前事件不允许穿戴装备。",
        )

    async def unequip_equipment(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.equipment.unequip(context),
            write_message="当前事件不允许卸下装备。",
        )

    async def get_companion_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.status(context), require_write=False)

    async def bond_companion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.bond(context), write_message="当前事件不允许结缘灵兽。")

    async def feed_companion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.feed(context), write_message="当前事件不允许喂养灵兽。")

    async def company_companion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context, lambda: self.companions.company(context), write_message="当前事件不允许与灵兽相伴。"
        )

    async def rest_companion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.rest(context), write_message="当前事件不允许休养灵兽。")

    async def equip_companion_gear(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.equip(context), write_message="当前事件不允许装备灵具。")

    async def evolve_companion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.companions.evolve(context), write_message="当前事件不允许蜕变灵兽。")

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

    async def create_purchase_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.create(context), write_message="当前事件不允许发布求购。")

    async def list_purchase_orders(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.list(context), require_write=False)

    async def match_purchase_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.match(context), write_message="当前事件不允许匹配求购。")

    async def deliver_purchase_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.deliver(context), write_message="当前事件不允许交付求购。")

    async def cancel_purchase_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.cancel(context), write_message="当前事件不允许取消求购。")

    async def expire_purchase_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.purchase_orders.expire(context), write_message="当前事件不允许清理求购。")

    async def cancel_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.cancel_market_order(context), write_message="当前事件不允许取消摆摊。")

    async def expire_market_order(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.expire_market_order(context), write_message="当前事件不允许清理摆摊。")

    async def list_market_orders(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.economy.list_market_orders(context), require_write=False)

    async def execute_cross_realm_trade(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.cross_realm_trade.execute(context),
            write_message="当前事件不允许执行跨界贸易。",
        )

    async def preview_void_market(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_market.preview(context),
            require_write=False,
        )

    async def purchase_void_market_offer(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_market.purchase(context),
            write_message="当前事件不允许购买虚空物资。",
        )

    async def void_material_board(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_material.board(context),
            require_write=False,
        )

    async def list_void_material(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_material.list_item(context),
            write_message="当前事件不允许寄售物资。",
        )

    async def buy_void_material(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_material.buy(context),
            write_message="当前事件不允许购入寄售。",
        )

    async def cancel_void_material(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.void_material.cancel(context),
            write_message="当前事件不允许撤下寄售。",
        )

    async def partner_task_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.partner_task.status(context),
            require_write=False,
        )

    async def start_partner_task(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.partner_task.start(context),
            write_message="当前事件不允许开启道侣协作。",
        )

    async def claim_partner_task(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.partner_task.claim(context),
            write_message="当前事件不允许领取道侣协作。",
        )

    async def ascension_day_overview(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.ascension_day.preview(context),
            require_write=False,
        )

    async def dao_route_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_route.status(context),
            require_write=False,
        )

    async def cast_dao_route_vote(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_route.vote(context),
            write_message="当前事件不允许道统议事。",
        )

    async def settle_dao_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_route.settle(context),
            write_message="当前事件不允许道统结算。",
        )

    async def dao_hall_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.status(context),
            require_write=False,
        )

    async def found_dao_hall(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.found(context),
            write_message="当前事件不允许开辟据点。",
        )

    async def join_dao_hall(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.join(context),
            write_message="当前事件不允许加入据点。",
        )

    async def leave_dao_hall(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.leave(context),
            write_message="当前事件不允许退出据点。",
        )

    async def build_dao_hall_project(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.build(context),
            write_message="当前事件不允许建设据点。",
        )

    async def maintain_dao_hall(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.dao_hall.maintain(context),
            write_message="当前事件不允许维护据点。",
        )

    async def device_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.device.status(context),
            require_write=False,
        )

    async def assemble_device(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.device.assemble(context),
            write_message="当前事件不允许组装机关。",
        )

    async def deploy_device(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.device.deploy(context),
            write_message="当前事件不允许部署机关。",
        )

    async def recall_device(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.device.recall(context),
            write_message="当前事件不允许收回机关。",
        )

    async def repair_device(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.device.repair(context),
            write_message="当前事件不允许维修机关。",
        )

    async def claim_path_switch_token(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_switch.claim_token(context),
            write_message="当前事件不允许请领转修令。",
        )

    async def preview_path_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_switch.preview(context),
            write_message="当前事件不允许预览转修。",
        )

    async def confirm_path_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_switch.confirm(context),
            write_message="当前事件不允许确认转修。",
        )

    async def cancel_path_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_switch.cancel(context),
            write_message="当前事件不允许取消转修。",
        )

    async def preview_path_rebuild(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_rebuild.preview(context),
            write_message="当前事件不允许预览道途重构。",
        )

    async def confirm_path_rebuild(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_rebuild.confirm(context),
            write_message="当前事件不允许确认道途重构。",
        )

    async def cancel_path_rebuild(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.path_rebuild.cancel(context),
            write_message="当前事件不允许取消道途重构。",
        )

    async def preview_subprofession_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.subprofession_switch.preview(context),
            write_message="当前事件不允许预览辅修切换。",
        )

    async def confirm_subprofession_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.subprofession_switch.confirm(context),
            write_message="当前事件不允许确认辅修切换。",
        )

    async def cancel_subprofession_switch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.subprofession_switch.cancel(context),
            write_message="当前事件不允许取消辅修切换。",
        )

    async def create_auction(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.auction.create(context),
            write_message="当前事件不允许发布拍卖。",
        )

    async def list_auctions(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.auction.list(context), require_write=False)

    async def bid_auction(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.auction.bid(context),
            write_message="当前事件不允许竞价。",
        )

    async def settle_auction(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.auction.settle(context),
            write_message="当前事件不允许结算拍卖。",
        )

    async def get_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_spirit_spring_event(context), require_write=False)

    async def get_heart_demon_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_heart_demon_event(context), require_write=False)

    async def claim_spirit_spring_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.events.claim_spirit_spring_event(context),
            write_message="当前事件不允许领取灵泉事件奖励。",
        )

    async def get_demon_invasion_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_demon_invasion_event(context), require_write=False)

    async def contribute_demon_invasion(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.contribute_demon_invasion(context), write_message="当前事件不允许贡献魔界战场。")

    async def claim_demon_invasion_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.events.claim_demon_invasion_event(context),
            write_message="当前事件不允许领取魔界入侵奖励。",
        )

    async def get_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_beast_trade_event(context), require_write=False)

    async def contribute_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.contribute_beast_trade_event(context), write_message="当前事件不允许贡献妖界贸易。")

    async def claim_beast_trade_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.claim_beast_trade_event(context), write_message="当前事件不允许领取妖界贸易奖励。")

    async def get_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_boundary_rift_event(context), require_write=False)

    async def contribute_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.contribute_boundary_rift_event(context), write_message="当前事件不允许贡献界隙裂痕。")

    async def claim_boundary_rift_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.claim_boundary_rift_event(context), write_message="当前事件不允许领取界隙裂痕奖励。")

    async def get_ancient_domain_open_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.get_ancient_domain_open_event(context), require_write=False)

    async def contribute_ancient_domain_open_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.contribute_ancient_domain_open_event(context), write_message="当前事件不允许贡献远古洞天。")

    async def claim_ancient_domain_open_event(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.events.claim_ancient_domain_open_event(context), write_message="当前事件不允许领取远古洞天开门奖励。")

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

    async def get_three_realms_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms_seasons.get_three_realms_season(context),
            require_write=False,
        )

    async def claim_three_realms_rewards(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms_seasons.claim_three_realms_rewards(context),
            write_message="当前事件不允许领取三界赛季奖励。",
        )

    async def get_domain_front(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.get_domain_front(context), require_write=False)

    async def join_domain_front(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.join_domain_front(context), write_message="当前事件不允许加入领域前线。")

    async def start_domain_front_battle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.start_domain_front_battle(context), write_message="当前事件不允许开始领域战。")

    async def create_domain_front_point(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.create_domain_front_point(context), write_message="当前事件不允许占领领域据点。")

    async def contribute_domain_front(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.contribute_domain_front(context), write_message="当前事件不允许贡献领域前线。")

    async def claim_domain_front_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.claim_domain_front_reward(context), write_message="当前事件不允许领取领域前线奖励。")

    async def get_domain_war_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.get_domain_war_season(context), require_write=False)

    async def claim_domain_war_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.claim_domain_war_reward(context), write_message="当前事件不允许领取领域战赛季奖励。")

    async def redeem_domain_core(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.domain_front.redeem_domain_core(context), write_message="当前事件不允许兑换领域核心。")

    async def publish_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.publish_snapshot(context),
            write_message="当前事件不允许发布竞技场防守快照。",
        )

    async def publish_three_realms_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.publish_three_realms_snapshot(context),
            write_message="当前事件不允许发布三界竞技场防守快照。",
        )

    async def revoke_arena_snapshot(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.revoke_snapshot(context),
            write_message="当前事件不允许撤销竞技场防守快照。",
        )

    async def list_arena_snapshots(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.arena.list_snapshots(context), require_write=False)

    async def list_three_realms_arena_snapshots(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.arena.list_three_realms_snapshots(context), require_write=False)

    async def challenge_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.challenge(context),
            write_message="当前事件不允许发起竞技场挑战。",
        )

    async def challenge_three_realms_arena(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.challenge_three_realms(context),
            write_message="当前事件不允许发起三界竞技场挑战。",
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

    async def arena_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.arena.season(context), require_write=False)

    async def claim_arena_season(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.arena.claim_season(context),
            write_message="当前事件不允许领取竞技场赛季奖励。",
        )

    async def spar_players(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.spar.spar(context), require_write=False)

    async def preview_idle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.idle.preview(context), require_write=False)

    async def start_idle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.idle.start(context), write_message="当前事件不允许开始挂机。")

    async def claim_idle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.idle.claim(context), write_message="当前事件不允许领取挂机收益。")

    async def cancel_idle(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.idle.cancel(context), write_message="当前事件不允许取消挂机。")

    async def preview_dispatch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.dispatch.preview(context), require_write=False)

    async def accept_dispatch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.dispatch.accept(context), write_message="当前事件不允许接受派遣。")

    async def settle_dispatch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.dispatch.settle(context), write_message="当前事件不允许结算派遣。")

    async def cancel_dispatch(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.dispatch.cancel(context), write_message="当前事件不允许取消派遣。")

    async def get_codex(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.codex.get_codex(context), require_write=False)

    async def claim_codex_milestone(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.codex.claim_milestone(context),
            write_message="当前事件不允许领取图鉴里程碑。",
        )

    async def preview_tower(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.tower.preview(context), require_write=False)

    async def challenge_tower(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.tower.challenge(context), write_message="当前事件不允许挑战试炼塔。")

    async def claim_tower_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.tower.claim_reward(context), write_message="当前事件不允许领取试炼塔奖励。")

    async def preview_void_spire(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_spire.preview(context), require_write=False)

    async def challenge_void_spire(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_spire.challenge(context), write_message="当前事件不允许挑战虚空塔。")

    async def claim_void_spire_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.void_spire.claim_reward(context), write_message="当前事件不允许领取虚空塔奖励。")

    async def preview_three_realms_tower(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.three_realms_tower.preview(context), require_write=False)

    async def challenge_three_realms_tower(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms_tower.challenge(context),
            write_message="当前事件不允许挑战三界塔。",
        )

    async def claim_three_realms_tower_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(
            context,
            lambda: self.three_realms_tower.claim_reward(context),
            write_message="当前事件不允许领取三界塔奖励。",
        )

    async def challenge_three_realms_tower_duo(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.three_realms_tower_duo.challenge(context), write_message="当前事件不允许挑战三界塔双人。")

    async def claim_three_realms_tower_duo_reward(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.three_realms_tower_duo.claim_reward(context), write_message="当前事件不允许领取三界塔双人奖励。")

    async def get_story_status(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.story.status(context), require_write=False)

    async def start_story(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.story.start(context), write_message="当前事件不允许开始剧情。")

    async def choose_story_route(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.story.choose(context), write_message="当前事件不允许选择剧情路线。")

    async def claim_story_ending(self, context: CommandContext) -> CommandResult:
        return await self._invoke(context, lambda: self.story.claim(context), write_message="当前事件不允许领取剧情结局。")

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
