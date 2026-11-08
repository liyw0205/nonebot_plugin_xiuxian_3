from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import (
    idle_route_definitions,
    reward_for,
)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, request: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id="",
        can_write_assets=True,
    )


def _row(result, key: str):
    return next(item for item in result.data["routes"] if item["route_key"] == key)


def test_endgame_routes_load_with_reachable_gates_and_pools() -> None:
    definitions = idle_route_definitions()
    # 13 routes through the seeker slice, plus the two unlock-gated watch routes
    # added by the codex-unlock consumers slice.
    assert len(definitions) == 15

    refuge = definitions["idle.domain_refuge_watch"]
    assert refuge.required_project_contribution == ("project.domain_refuge", 10)
    assert refuge.required_dao_route is False
    assert refuge.duration_seconds == 36000
    assert refuge.stamina_cost == 3
    assert refuge.daily_limit == 1

    supply = definitions["idle.void_supply_watch"]
    assert (supply.required_realm, supply.required_layer) == ("void_refining", 1)
    assert supply.duration_seconds == 43200
    assert supply.stamina_cost == 4

    settlement = definitions["idle.dao_settlement_watch"]
    assert settlement.required_dao_route is True
    assert settlement.required_realm is None
    assert settlement.duration_seconds == 43200

    for definition in (refuge, supply, settlement):
        full = reward_for(definition, "endgame:seed", fallback=False)
        fallback = reward_for(definition, "endgame:seed", fallback=True)
        assert full and fallback
        assert "spirit_stones" in fallback
        assert len(fallback) == 1


def test_endgame_route_preview_enforces_contribution_realm_and_dao_route() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "idle-endgame-gates"
            created = await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
            assert created.ok, created.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=4 "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            async def preview(route: str, request: str):
                result = await runtime.dispatch(
                    _context(adapter, user, request), f"挂机预览 {route}"
                )
                assert result.code == "IDLE_PREVIEW", result.message
                return result

            refuge = _row(await preview("领域避难所看守", "refuge-blocked"), "idle.domain_refuge_watch")
            assert refuge["ready"] is False
            assert "参与度不足（需要 10 点）" in refuge["missing"]
            assert refuge["requirements"]["required_project_contribution"] == [
                "project.domain_refuge",
                10,
            ]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                now = clock.value.isoformat()
                connection.execute(
                    "INSERT INTO livelihood_projects(project_id, project_key, business_week, "
                    "status, target_points, contribution_points, requirements_json, progress_json, "
                    "effect_key, snapshot_json, result_json, created_at, updated_at) "
                    "VALUES ('project-row-1', 'project.domain_refuge', '2026-W39', 'active', 10, 10, "
                    "'{}', '{}', 'effect.domain_refuge', '{}', '{}', ?, ?)",
                    (now, now),
                )
                connection.execute(
                    "INSERT INTO livelihood_project_contributions(contribution_id, project_id, "
                    "player_id, operation_id, source_operation_id, contribution_kind, service_key, "
                    "quantity, resource_key, resource_amount, contribution_points, created_at) "
                    "VALUES ('contrib-row-1', 'project-row-1', ?, 'contrib-op-1', 'source-op-1', "
                    "'resource', '', 10, 'item.mat.wood', 10, 10, ?)",
                    (player_id, now),
                )
            refuge = _row(await preview("领域避难所看守", "refuge-allowed"), "idle.domain_refuge_watch")
            assert refuge["ready"] is True, refuge["missing"]

            supply = _row(await preview("虚空补给看守", "supply-blocked"), "idle.void_supply_watch")
            assert supply["ready"] is False
            assert "境界不足" in supply["missing"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='void_refining', realm_layer=1 WHERE id=?",
                    (player_id,),
                )
            supply = _row(await preview("虚空补给看守", "supply-allowed"), "idle.void_supply_watch")
            assert supply["ready"] is True, supply["missing"]

            settlement = _row(
                await preview("道统据点看守", "settlement-blocked"), "idle.dao_settlement_watch"
            )
            assert settlement["ready"] is False
            assert "需要宗门已定道统" in settlement["missing"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                now = clock.value.isoformat()
                connection.execute(
                    "INSERT INTO sects(sect_id, name, name_key, leader_id, status, level, "
                    "max_members, warehouse_capacity, construction, spirit_stones, sect_merit, "
                    "warehouse_json, created_at, updated_at) "
                    "VALUES ('sect-endgame', '终局宗', 'sect-endgame:name', ?, 'active', 6, 80, 100, "
                    "0, 0, 1000, '{}', ?, ?)",
                    (player_id, now, now),
                )
                connection.execute(
                    "INSERT INTO sect_members(sect_id, player_id, role, status, contribution, "
                    "joined_at, last_action_at, created_at, updated_at) "
                    "VALUES ('sect-endgame', ?, 'leader', 'active', 0, ?, ?, ?, ?)",
                    (player_id, now, now, now, now),
                )
                connection.execute(
                    "INSERT INTO dao_route_state(sect_id, route_key, cycle_id, locked_until, "
                    "updated_at) VALUES ('sect-endgame', 'route.dao_settlement.remain', 'route:test', ?, ?)",
                    ((clock.value + timedelta(days=7)).isoformat(), now),
                )
            settlement = _row(
                await preview("道统据点看守", "settlement-allowed"), "idle.dao_settlement_watch"
            )
            assert settlement["ready"] is True, settlement["missing"]

            base = _row(await preview("镇中行旅", "base-route"), "idle.town_errand")
            assert "参与度不足（需要 10 点）" not in base["missing"]
            assert "需要宗门已定道统" not in base["missing"]
            await runtime.close()

    asyncio.run(run())
