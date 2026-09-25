from __future__ import annotations

from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import RepositoryBusyError
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository
from nonebot_plugin_xiuxian_3.xiuxian.repository import RepositoryBusyError as CompatibilityBusyError


def test_sqlite_repository_composes_domain_transaction_mixins() -> None:
    expected_modules = {
        "create_player": "nonebot_plugin_xiuxian_3.xiuxian.player.repository",
        "start_travel": "nonebot_plugin_xiuxian_3.xiuxian.world.travel_repository",
        "board_cloud_boat": "nonebot_plugin_xiuxian_3.xiuxian.world.cloud_repository",
        "settle_cloud_boat": "nonebot_plugin_xiuxian_3.xiuxian.world.cloud_repository",
        "recover_cloud_boat": "nonebot_plugin_xiuxian_3.xiuxian.world.cloud_repository",
        "accept_demon_intro": "nonebot_plugin_xiuxian_3.xiuxian.world.cloud_repository",
        "use_array_hall": "nonebot_plugin_xiuxian_3.xiuxian.world.cloud_repository",
        "start_void_route": "nonebot_plugin_xiuxian_3.xiuxian.world.repository",
        "recover_resources": "nonebot_plugin_xiuxian_3.xiuxian.progression.repository",
        "enter_cultivation": "nonebot_plugin_xiuxian_3.xiuxian.progression.cultivation_repository",
        "start_breakthrough": "nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.repository",
        "start_retreat": "nonebot_plugin_xiuxian_3.xiuxian.advancement.repository",
        "lease_residence": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.repository",
        "plant_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.field_repository",
        "maintain_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.field_repository",
        "harvest_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.field_repository",
        "list_commissions": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "accept_commission": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "deliver_commission": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "preview_route": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_repository",
        "start_route": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_repository",
        "settle_route": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_repository",
        "publish_service": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.service_repository",
        "accept_service": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.service_repository",
        "cancel_service": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.service_repository",
        "settle_service": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.service_repository",
        "list_projects": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.project_repository",
        "contribute_project": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.project_repository",
        "settle_project": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.project_repository",
        "create_sect": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "apply_sect": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "list_sect_applications": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "review_sect_application": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "leave_sect": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "get_sect_profile": "nonebot_plugin_xiuxian_3.xiuxian.social.sect_repository",
        "create_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "invite_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "accept_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "reject_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "confirm_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "leave_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "get_party": "nonebot_plugin_xiuxian_3.xiuxian.social.party_repository",
        "invite_mentor": "nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository",
        "accept_mentor": "nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository",
        "reject_mentor": "nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository",
        "graduate_apprentice": "nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository",
        "start_production": "nonebot_plugin_xiuxian_3.xiuxian.production.repository",
        "start_exploration": "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository",
        "accept_bounty": "nonebot_plugin_xiuxian_3.xiuxian.adventures.repository",
        "get_dao_echoes_status": "nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes_repository",
        "start_dao_echoes_stage": "nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes_repository",
        "claim_dao_echoes_stage": "nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes_repository",
        "claim_daily": "nonebot_plugin_xiuxian_3.xiuxian.routine.repository",
        "begin_dao_union": "nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_repository",
        "preview_final_battle": "nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_repository",
        "choose_ending": "nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_repository",
        "create_market_order": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "buy_market_order": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "cancel_market_order": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "create_production_commission": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "accept_production_commission": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "deliver_production_commission": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "settle_production_commission": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "cancel_production_commission": "nonebot_plugin_xiuxian_3.xiuxian.economy.repository",
        "get_spirit_spring_event": "nonebot_plugin_xiuxian_3.xiuxian.events.repository",
        "claim_spirit_spring_event": "nonebot_plugin_xiuxian_3.xiuxian.events.repository",
        "get_final_heaven_season": "nonebot_plugin_xiuxian_3.xiuxian.events.season_repository",
        "claim_final_heaven_rewards": "nonebot_plugin_xiuxian_3.xiuxian.events.season_repository",
        "get_advanced_quests": "nonebot_plugin_xiuxian_3.xiuxian.quests.repository",
        "complete_domain_material_commission": "nonebot_plugin_xiuxian_3.xiuxian.quests.repository",
        "complete_ancient_domain_line": "nonebot_plugin_xiuxian_3.xiuxian.quests.repository",
        "claim_soul_transformation_quest": "nonebot_plugin_xiuxian_3.xiuxian.quests.repository",
        "claim_void_refining_quest": "nonebot_plugin_xiuxian_3.xiuxian.quests.repository",
        "claim_demon_mainline": "nonebot_plugin_xiuxian_3.xiuxian.quests.cross_realm_repository",
        "record_dao_union_mainline": "nonebot_plugin_xiuxian_3.xiuxian.quests.endgame_repository",
        "record_dao_union_challenge": "nonebot_plugin_xiuxian_3.xiuxian.quests.endgame_repository",
        "deliver_dao_union_work": "nonebot_plugin_xiuxian_3.xiuxian.quests.endgame_repository",
        "claim_dao_union_quest": "nonebot_plugin_xiuxian_3.xiuxian.quests.endgame_repository",
        "complete_dao_origin_task": "nonebot_plugin_xiuxian_3.xiuxian.quests.endgame_repository",
        "start_quest_battle": "nonebot_plugin_xiuxian_3.xiuxian.combat.repository",
    }

    assert {
        name: getattr(SQLitePlayerRepository, name).__module__
        for name in expected_modules
    } == expected_modules


def test_repository_facade_preserves_error_identity() -> None:
    assert CompatibilityBusyError is RepositoryBusyError
