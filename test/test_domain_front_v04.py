from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation, can_write_assets=True)


def _prepare_player(runtime, adapter: str, user: str, sect_id: str) -> int:
    now = runtime.repository._now().isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = int(connection.execute("SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, domain_key='domain.fire', location_key='xuantian.domain_front', stamina=100 WHERE id=?",
            (player_id,),
        )
        connection.execute(
            "INSERT INTO sects(sect_id,name,name_key,motto,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES (?, ?, ?, '', ?, 'active', 4, 20, 100, 0, 0, 0, '{}', ?, ?, 'content-0.4', 'social-0.4.0')",
            (sect_id, f"宗门{sect_id}", sect_id, player_id, now, now),
        )
        connection.execute(
            "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)",
            (sect_id, player_id, now, now, now, now),
        )
    return player_id


def test_domain_front_round_and_season_are_playable_on_qq_and_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                user = f"domain-{adapter}"
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                assert created.ok
                _prepare_player(runtime, adapter, user, f"sect-{adapter}")

                status = await runtime.adapters.dispatch(adapter, _context(adapter, user, "status"), "领域前线")
                assert status.code == "DOMAIN_EVENT_STATUS"
                round_id = status.data["round_id"]
                joined = await runtime.adapters.dispatch(adapter, _context(adapter, user, "join", "domain-join"), "加入领域前线")
                assert joined.code == "DOMAIN_EVENT_JOINED"
                battle = await runtime.adapters.dispatch(adapter, _context(adapter, user, "battle", "domain-battle"), "开始领域战")
                assert battle.code == "DOMAIN_BATTLE_SETTLED"
                contributed = await runtime.adapters.dispatch(adapter, _context(adapter, user, "contribute", "domain-contribution"), "贡献领域前线 战斗")
                assert contributed.code == "DOMAIN_EVENT_CONTRIBUTION_RECORDED"
                replay = await runtime.adapters.dispatch(adapter, _context(adapter, user, "contribute-replay", "domain-contribution"), "贡献领域前线 战斗")
                assert replay.data["idempotent_replay"] is True

                # Season score is projected from all three server-owned sources.
                now = clock.value.isoformat()
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO sect_contribution_events(sect_id,player_id,source_operation_id,quantity,occurred_at) VALUES (?, ?, ?, ?, ?)",
                        (f"sect-{adapter}", player_id, f"sect-score-{adapter}", 7, now),
                    )
                    connection.execute(
                        "INSERT INTO production_orders(order_id,player_id,operation_id,recipe_key,status,starts_at,ends_at,energy_cost,currency_cost,facility_slot_id,snapshot_json,result_json,created_at,updated_at) VALUES (?, ?, ?, ?, 'completed', ?, ?, 0, 0, NULL, ?, '{}', ?, ?)",
                        (
                            f"production-score-{adapter}",
                            player_id,
                            f"production-score-op-{adapter}",
                            "recipe.masterwork.body",
                            now,
                            now,
                            json.dumps({"realm_key": "soul_transformation"}),
                            now,
                            now,
                        ),
                    )

                clock.advance(minutes=31)
                settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settled"), f"领域前线 {round_id}")
                assert settled.data["status"] == "settled"
                claimed = await runtime.adapters.dispatch(adapter, _context(adapter, user, "claim", "domain-claim"), f"领取领域前线奖励 {round_id}")
                assert claimed.code == "DOMAIN_EVENT_REWARD_CLAIMED"
                claim_replay = await runtime.adapters.dispatch(adapter, _context(adapter, user, "claim-replay", "domain-claim"), f"领取领域前线奖励 {round_id}")
                assert claim_replay.data["idempotent_replay"] is True

                season = await runtime.adapters.dispatch(adapter, _context(adapter, user, "season"), "领域赛季")
                season_id = season.data["season_id"]
                before_close = await runtime.adapters.dispatch(adapter, _context(adapter, user, "redeem-before-close", "domain-core-before-close"), f"兑换领域核心 {season_id}")
                assert before_close.code == "DOMAIN_CORE_REDEEM_NOT_AVAILABLE"
                clock.advance(days=21)
                frozen = await runtime.adapters.dispatch(adapter, _context(adapter, user, "freeze"), f"领域赛季 {season_id}")
                assert frozen.data["status"] == "frozen"
                assert frozen.data["personal"]["rank"] == 1
                assert frozen.data["personal"]["score"] == 119
                season_claim = await runtime.adapters.dispatch(adapter, _context(adapter, user, "season-claim", "domain-season-claim"), f"领取领域赛季奖励 {season_id}")
                assert season_claim.code == "DOMAIN_SEASON_REWARD_CLAIMED"
                redeemed = await runtime.adapters.dispatch(adapter, _context(adapter, user, "redeem", "domain-core-redeem"), f"兑换领域核心 {season_id}")
                assert redeemed.code == "DOMAIN_CORE_REDEEMED"
                redeem_replay = await runtime.adapters.dispatch(adapter, _context(adapter, user, "redeem-replay", "domain-core-redeem"), f"兑换领域核心 {season_id}")
                assert redeem_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, merit = connection.execute("SELECT inventory_json, world_merit FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()
                assert json.loads(inventory)["item.domain_core_fragment"] == 5
                assert json.loads(inventory)["item.domain_core"] == 1
                assert merit == 100
                await runtime.close()

    asyncio.run(run())


def test_domain_front_rejects_crack_and_sect_cap_without_spending_stamina() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            adapter = "qq.official"
            first, second = "domain-cap-1", "domain-cap-2"
            assert (await runtime.adapters.dispatch(adapter, _context(adapter, first, "create"), "开始修仙")).ok
            assert (await runtime.adapters.dispatch(adapter, _context(adapter, second, "create"), "开始修仙")).ok
            _prepare_player(runtime, adapter, first, "sect-cap")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                first_id = connection.execute("SELECT id FROM players WHERE platform_user_id=?", (first,)).fetchone()[0]
                second_id = connection.execute("SELECT id FROM players WHERE platform_user_id=?", (second,)).fetchone()[0]
                connection.execute("UPDATE players SET domain_crack_until=? WHERE id=?", ((clock.value + timedelta(hours=1)).isoformat(), first_id))
                connection.execute("UPDATE players SET stage='cultivator',realm_key='soul_transformation',realm_layer=1,domain_key='domain.fire',location_key='xuantian.domain_front',stamina=100 WHERE id=?", (second_id,))
                now = clock.value.isoformat()
                connection.execute("INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('sect-cap',?,'member','active',0,?,?,?,?)", (second_id, now, now, now, now))
            denied = await runtime.adapters.dispatch(adapter, _context(adapter, first, "crack", "crack-join"), "加入领域前线")
            assert denied.code == "DOMAIN_CRACK_ACTIVE"
            joined = await runtime.adapters.dispatch(adapter, _context(adapter, second, "join", "second-join"), "加入领域前线")
            assert joined.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute("SELECT stamina FROM players WHERE platform_user_id=?", (first,)).fetchone()[0]
            assert stamina == 100
            await runtime.close()

    asyncio.run(run())
