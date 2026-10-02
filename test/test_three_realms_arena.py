from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
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


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation,
        operation_id=operation,
        can_write_assets=True,
    )


async def _prepare_player(runtime, adapter: str, user: str, *, faction: str, permit: bool = True) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{adapter}:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    inventory = {"item.bound.test": 2}
    flags = [f"alliance.{faction}"]
    if permit:
        inventory["item.permit.three_realms_arena"] = 1
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                arena_rating=1000, max_hp=1000, initiative=40, pollution=37,
                bloodline_stability=63, spirit_stones=777,
                qualification_json=?, intro_json=?, inventory_json=?, faction_reputation_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({"body": 40, "agility": 40, "alliance_key": faction}),
                json.dumps({"flags": flags}),
                json.dumps(inventory),
                json.dumps({"xuantian": 100, "demon": 200, "beast": 300}),
                adapter,
                user,
            ),
        )


def test_three_realms_arena_cross_faction_freezes_context_across_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _prepare_player(runtime, "qq.official", "three-qq", faction="xuantian")
            await _prepare_player(runtime, "onebot.v11", "three-ob", faction="demon")

            qq_publish = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", "three-qq", "qq-publish"), "发布三界竞技场快照"
            )
            ob_publish = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", "three-ob", "ob-publish"), "发布三界竞技场快照"
            )
            assert qq_publish.code == ob_publish.code == "ARENA_SNAPSHOT_PUBLISHED"
            assert qq_publish.data["mode_key"] == "arena.three_realms"
            snapshot_id = str(ob_publish.data["snapshot_id"])

            before = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", "three-qq", "qq-before"), "挑战三界竞技场 " + snapshot_id
            )
            assert before.code == "ARENA_MATCH_NOT_ALLOWED"
            clock.advance(minutes=31)
            listed = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", "three-qq", "qq-list"), "三界竞技场列表"
            )
            assert listed.code == "ARENA_SNAPSHOT_LIST"
            assert listed.data["snapshots"][0]["snapshot_id"] == snapshot_id

            result = await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "three-qq", "qq-challenge"),
                "挑战三界竞技场 " + snapshot_id,
            )
            assert result.code == "ARENA_MATCH_SETTLED", result.message
            assert result.data["mode_key"] == "arena.three_realms"
            match_id = str(result.data["match_id"])
            replay = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", "three-ob", "ob-replay"), "竞技场回放 " + match_id
            )
            assert replay.code == "ARENA_REPLAY"
            environment = replay.data["result"]["tactical_environment"]
            assert environment["relation"] == "cross_faction"
            assert environment["challenger_faction"] == "xuantian"
            assert environment["defender_faction"] == "demon"
            assert replay.data["snapshot"]["challenger"]["pollution"] == 37
            assert replay.data["snapshot"]["defender"]["bloodline_stability"] == 63

            replayed = await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "three-qq", "qq-challenge"),
                "挑战三界竞技场 " + snapshot_id,
            )
            assert replayed.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform, platform_user_id, spirit_stones, inventory_json, faction_reputation_json, pollution, bloodline_stability FROM players WHERE platform_user_id LIKE 'three-%' ORDER BY platform_user_id"
                ).fetchall()
                assert all(row[2] == 777 for row in rows)
                assert all(json.loads(row[3])["item.bound.test"] == 2 for row in rows)
                assert all(json.loads(row[4]) == {"xuantian": 100, "demon": 200, "beast": 300} for row in rows)
                assert [(row[5], row[6]) for row in rows] == [(37, 63), (37, 63)]
                snapshot = connection.execute(
                    "SELECT snapshot_json FROM arena_snapshots WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()[0]
                assert json.loads(snapshot)["alliance_key"] == "demon"
                assert connection.execute(
                    "SELECT COUNT(*) FROM arena_matches WHERE arena_mode_key='arena.three_realms'"
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_three_realms_arena_same_faction_and_missing_permit_are_gated() -> None:
    async def run() -> None:
        for adapter, user in (("qq.official", "three-gate-qq"), ("onebot.v11", "three-gate-ob")):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir)
                await _prepare_player(runtime, adapter, user, faction="beast", permit=False)
                denied = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"denied-{adapter}"), "发布三界竞技场快照"
                )
                assert denied.code == "THREE_REALMS_ARENA_REQUIREMENT_MISSING"
                await runtime.close()

        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _prepare_player(runtime, "qq.official", "same-qq", faction="beast")
            await _prepare_player(runtime, "onebot.v11", "same-ob", faction="beast")
            left = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", "same-qq", "same-publish"), "发布三界竞技场快照"
            )
            right = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", "same-ob", "same-publish-ob"), "发布三界竞技场快照"
            )
            clock.advance(minutes=31)
            result = await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "same-qq", "same-challenge"),
                "挑战三界竞技场 " + str(right.data["snapshot_id"]),
            )
            assert left.code == right.code == "ARENA_SNAPSHOT_PUBLISHED"
            assert result.code == "ARENA_MATCH_SETTLED"
            replay = await runtime.adapters.dispatch(
                "onebot.v11",
                _ctx("onebot.v11", "same-ob", "same-replay"),
                "竞技场回放 " + str(result.data["match_id"]),
            )
            assert replay.data["result"]["tactical_environment"]["relation"] == "same_faction"
            await runtime.close()

    asyncio.run(run())
