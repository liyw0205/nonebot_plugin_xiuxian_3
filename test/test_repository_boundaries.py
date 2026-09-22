from __future__ import annotations

from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import RepositoryBusyError
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository
from nonebot_plugin_xiuxian_3.xiuxian.repository import RepositoryBusyError as CompatibilityBusyError


def test_sqlite_repository_composes_domain_transaction_mixins() -> None:
    expected_modules = {
        "create_player": "nonebot_plugin_xiuxian_3.xiuxian.player.repository",
        "start_travel": "nonebot_plugin_xiuxian_3.xiuxian.world.travel_repository",
        "start_void_route": "nonebot_plugin_xiuxian_3.xiuxian.world.repository",
        "recover_resources": "nonebot_plugin_xiuxian_3.xiuxian.progression.repository",
        "enter_cultivation": "nonebot_plugin_xiuxian_3.xiuxian.progression.cultivation_repository",
        "start_breakthrough": "nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.repository",
        "start_retreat": "nonebot_plugin_xiuxian_3.xiuxian.advancement.repository",
        "lease_residence": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.repository",
        "plant_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.repository",
        "maintain_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.repository",
        "harvest_plot": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.repository",
        "list_commissions": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "accept_commission": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "deliver_commission": "nonebot_plugin_xiuxian_3.xiuxian.livelihood.commission_repository",
        "start_production": "nonebot_plugin_xiuxian_3.xiuxian.production.repository",
        "start_exploration": "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository",
        "accept_bounty": "nonebot_plugin_xiuxian_3.xiuxian.adventures.repository",
        "claim_daily": "nonebot_plugin_xiuxian_3.xiuxian.routine.repository",
        "begin_dao_union": "nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_repository",
    }

    assert {
        name: getattr(SQLitePlayerRepository, name).__module__
        for name in expected_modules
    } == expected_modules


def test_repository_facade_preserves_error_identity() -> None:
    assert CompatibilityBusyError is RepositoryBusyError
