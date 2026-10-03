from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import idle_route_definitions


ROOT = Path(__file__).parents[1]


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _command(runtime, adapter: str, user: str, operation_id: str, text: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), text)


async def _create_player(runtime, adapter: str, user: str) -> None:
    assert (await _command(runtime, adapter, user, f"{user}-create", "开始修仙")).ok
    assert (await _command(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok


def _copy_content(target: Path) -> Path:
    content = target / "data"
    shutil.copytree(
        ROOT / "data",
        content,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return content


def _set_local_reputation(runtime, adapter: str, user: str, value: int) -> None:
    with runtime.repository._connect() as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json",
            (player_id, json.dumps({"local.xuantian.new_town": value}), "2026-09-01T00:00:00+00:00"),
        )


def _set_player_local_json(runtime, adapter: str, user: str, value: str) -> None:
    with runtime.repository._connect() as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json",
            (player_id, value, "2026-09-01T00:00:00+00:00"),
        )


def test_idle_route_json_drives_rules_and_frozen_settlement_across_adapters(tmp_path: Path) -> None:
    content = _copy_content(tmp_path)
    livelihood_path = content / "生活" / "生活.json"
    livelihood = json.loads(livelihood_path.read_text(encoding="utf-8"))
    town = next(row for row in livelihood["records"] if row.get("key") == "idle.town_errand")
    town["duration_seconds"] = 3600
    town["desc"] = "替镇中商铺理清今日账册。"
    livelihood_path.write_text(json.dumps(livelihood, ensure_ascii=False, indent=2), encoding="utf-8")

    reward_path = content / "奖励" / "奖励.json"
    rewards = json.loads(reward_path.read_text(encoding="utf-8"))
    town_pool = next(
        row for row in rewards["records"] if row.get("key") == "reward_pool.idle.town_errand"
    )
    town_pool["outcomes"] = [
        {"weight": 1, "rewards": {"spirit_stones": 77, "local.xuantian.new_town": 2}}
    ]
    reward_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2), encoding="utf-8")

    locations_path = content / "地图" / "地点.json"
    locations = json.loads(locations_path.read_text(encoding="utf-8"))
    new_town = next(row for row in locations["records"] if row.get("key") == "xuantian.new_town")
    new_town["local_reputation_maximum"] = 41
    locations_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
        starts = {}
        try:
            for adapter, user in (("qq.official", "idle-json-qq"), ("onebot.v11", "idle-json-ob")):
                await _create_player(runtime, adapter, user)
                _set_local_reputation(runtime, adapter, user, 40)
                preview = await _command(
                    runtime, adapter, user, f"{user}-preview", "挂机预览 镇中行旅"
                )
                assert "替镇中商铺理清今日账册" in preview.message
                started = await _command(
                    runtime, adapter, user, f"{user}-start", "开始挂机 镇中行旅"
                )
                assert started.code == "IDLE_STARTED", started.message
                assert started.data["claim_at"].endswith("01:00:00+00:00")
                starts[adapter] = (user, started.data["assignment_id"])
                with runtime.repository._connect() as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM idle_assignments WHERE assignment_id = ?",
                            (started.data["assignment_id"],),
                        ).fetchone()[0]
                    )
                assert snapshot["full_reward"] == {
                    "spirit_stones": 77,
                    "local.xuantian.new_town": 2,
                }
                assert snapshot["local_reputation_maximums"] == {
                    "local.xuantian.new_town": 41
                }

            livelihood["records"] = [
                {**row, "duration_seconds": 7200} if row.get("key") == "idle.town_errand" else row
                for row in livelihood["records"]
            ]
            livelihood_path.write_text(
                json.dumps(livelihood, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            town_pool["outcomes"] = [
                {"weight": 1, "rewards": {"spirit_stones": 99, "local.xuantian.new_town": 2}}
            ]
            reward_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2), encoding="utf-8")
            new_town["local_reputation_maximum"] = 1
            locations_path.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await runtime.close()

            clock.advance(hours=1)
            runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
            for adapter, (user, assignment_id) in starts.items():
                operation = f"{user}-claim"
                claimed = await _command(runtime, adapter, user, operation, "领取挂机")
                assert claimed.code == "IDLE_CLAIMED", claimed.message
                assert claimed.data["reward"] == {
                    "spirit_stones": 77,
                    "local.xuantian.new_town": 1,
                }
                assert "idle.town_errand" not in claimed.message
                assert "local.xuantian.new_town" not in claimed.message
                conflict = await _command(
                    runtime,
                    adapter,
                    user,
                    operation,
                    f"领取挂机 {assignment_id}",
                )
                assert conflict.code == "OPERATION_CONFLICT"
            await runtime.close()

            runtime = create_runtime(data_dir=content, clock=clock, adapters=("qq.official", "onebot.v11"))
            for adapter, (user, _) in starts.items():
                replay = await _command(runtime, adapter, user, f"{user}-claim", "领取挂机")
                assert replay.code == "IDLE_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"]["spirit_stones"] == 77
            await runtime.close()
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_start_rejects_location_residence_and_reputation_gaps(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=_copy_content(tmp_path))
        try:
            for user in ("idle-location", "idle-residence", "idle-reputation"):
                await _create_player(runtime, "qq.official", user)
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET location_key = 'xuantian.outskirts' "
                    "WHERE platform_user_id = 'idle-location'"
                )
            _set_local_reputation(runtime, "qq.official", "idle-reputation", 19)
            for user, command in (
                ("idle-location", "开始挂机 镇中行旅"),
                ("idle-residence", "开始挂机 灵圃看护"),
                ("idle-reputation", "开始挂机 商道探路"),
            ):
                result = await _command(runtime, "qq.official", user, f"{user}-start", command)
                assert result.code == "IDLE_REQUIREMENT_MISSING", result.message
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM idle_assignments").fetchone()[0] == 0
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_claim_rejects_malformed_reputation_and_retries_same_operation(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(
            data_dir=_copy_content(tmp_path), clock=clock, adapters=("qq.official", "onebot.v11")
        )
        try:
            for adapter, user in (("qq.official", "idle-json-bad-qq"), ("onebot.v11", "idle-json-bad-ob")):
                await _create_player(runtime, adapter, user)
                started = await _command(
                    runtime, adapter, user, f"{user}-start", "开始挂机 镇中行旅"
                )
                assert started.code == "IDLE_STARTED"
            clock.advance(hours=2)
            for adapter, user in (("qq.official", "idle-json-bad-qq"), ("onebot.v11", "idle-json-bad-ob")):
                _set_player_local_json(runtime, adapter, user, "{")
                with runtime.repository._connect() as connection:
                    row = connection.execute(
                        "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    stones_before = row["spirit_stones"]
                operation = f"{user}-claim"
                failed = await _command(runtime, adapter, user, operation, "领取挂机")
                assert failed.code == "PERSISTENCE_ERROR"
                with runtime.repository._connect() as connection:
                    state = connection.execute(
                        "SELECT status FROM idle_assignments WHERE player_id = "
                        "(SELECT id FROM players WHERE platform = ? AND platform_user_id = ?)",
                        (adapter, user),
                    ).fetchone()
                    row = connection.execute(
                        "SELECT spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    assert state["status"] == "running"
                    assert row["spirit_stones"] == stones_before
                    assert connection.execute(
                        "SELECT 1 FROM operations WHERE operation_id = ?", (operation,)
                    ).fetchone() is None
                _set_player_local_json(runtime, adapter, user, "{}")
                retried = await _command(runtime, adapter, user, operation, "领取挂机")
                assert retried.code == "IDLE_CLAIMED", retried.message
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_claim_ledger_failure_rolls_back_and_retries(monkeypatch, tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(
            data_dir=_copy_content(tmp_path), clock=clock, adapters=("qq.official", "onebot.v11")
        )
        try:
            for adapter, user in (("qq.official", "idle-ledger-qq"), ("onebot.v11", "idle-ledger-ob")):
                await _create_player(runtime, adapter, user)
                started = await _command(
                    runtime, adapter, user, f"{user}-start", "开始挂机 镇中行旅"
                )
                assert started.code == "IDLE_STARTED"
            clock.advance(hours=2)
            original = runtime.repository._record_idle_operation

            def fail_claim(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
                if operation_name == "specials.claim_idle":
                    raise sqlite3.OperationalError("injected ledger failure")
                return original(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)

            monkeypatch.setattr(runtime.repository, "_record_idle_operation", fail_claim)
            for adapter, user in (("qq.official", "idle-ledger-qq"), ("onebot.v11", "idle-ledger-ob")):
                operation = f"{user}-claim"
                with runtime.repository._connect() as connection:
                    row = connection.execute(
                        "SELECT id, spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    before_stones = row["spirit_stones"]
                    before_local = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                    ).fetchone()
                failed = await _command(runtime, adapter, user, operation, "领取挂机")
                assert failed.code == "PERSISTENCE_ERROR"
                with runtime.repository._connect() as connection:
                    row = connection.execute(
                        "SELECT id, spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    assert row["spirit_stones"] == before_stones
                    assert connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                    ).fetchone() == before_local
                    assert connection.execute(
                        "SELECT status FROM idle_assignments WHERE player_id = ?", (row["id"],)
                    ).fetchone()["status"] == "running"
                    assert connection.execute(
                        "SELECT 1 FROM operations WHERE operation_id = ?", (operation,)
                    ).fetchone() is None
            monkeypatch.setattr(runtime.repository, "_record_idle_operation", original)
            for adapter, user in (("qq.official", "idle-ledger-qq"), ("onebot.v11", "idle-ledger-ob")):
                operation = f"{user}-claim"
                claimed = await _command(runtime, adapter, user, operation, "领取挂机")
                assert claimed.code == "IDLE_CLAIMED", claimed.message
                assert claimed.data["reward"]["local.xuantian.new_town"] == 2
                replay = await _command(runtime, adapter, user, operation, "领取挂机")
                assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_route_content_rejects_missing_reward_pool(tmp_path: Path) -> None:
    content = _copy_content(tmp_path)
    source = content / "生活" / "生活.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    route = next(row for row in document["records"] if row.get("key") == "idle.herb_watch")
    route["reward_pool_key"] = "reward_pool.missing"
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ContentError, match="idle route idle.herb_watch references invalid reward pool"):
        idle_route_definitions(ContentBundle.load(content))


def test_idle_route_scout_claim_records_its_configured_codex_entry(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=_copy_content(tmp_path), clock=clock)
        try:
            adapter, user = "onebot.v11", "idle-scout"
            await _create_player(runtime, adapter, user)
            _set_local_reputation(runtime, adapter, user, 20)
            started = await _command(runtime, adapter, user, f"{user}-start", "开始挂机 商道探路")
            assert started.code == "IDLE_STARTED", started.message
            clock.advance(hours=6)
            claimed = await _command(runtime, adapter, user, f"{user}-claim", "领取挂机")
            assert claimed.code == "IDLE_CLAIMED", claimed.message
            assert 25 <= claimed.data["reward"]["spirit_stones"] <= 40
            assert claimed.data["reward"]["codex.route.town_road"] == 1
            assert "青石镇商路" in claimed.message
            assert "codex.route.town_road" not in claimed.message
            with runtime.repository._connect() as connection:
                discovery = connection.execute(
                    "SELECT first_seen_operation_id FROM codex_entries "
                    "WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?) "
                    "AND entry_key = ?",
                    (user, "codex.route.town_road"),
                ).fetchone()
                assert discovery["first_seen_operation_id"] == f"{user}-claim"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_idle_daily_limit_counts_each_route_independently(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=_copy_content(tmp_path), clock=clock)
        try:
            adapter, user = "qq.official", "idle-route-daily"
            await _create_player(runtime, adapter, user)
            now = clock().isoformat()
            with runtime.repository._connect() as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO residences(residence_id, player_id, operation_id, residence_key, status, starts_at, ends_at, rent_cost, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'active', ?, ?, 0, ?, ?)",
                    (
                        "idle-daily-residence",
                        player_id,
                        "idle-daily-residence-op",
                        "residence.town_room",
                        now,
                        "2026-10-01T00:00:00+00:00",
                        now,
                        now,
                    ),
                )
            started = await _command(runtime, adapter, user, f"{user}-town-start", "开始挂机 镇中行旅")
            assert started.code == "IDLE_STARTED", started.message
            clock.advance(hours=2)
            town = await _command(runtime, adapter, user, f"{user}-town-claim", "领取挂机")
            assert town.code == "IDLE_CLAIMED", town.message
            herb = await _command(runtime, adapter, user, f"{user}-herb-start", "开始挂机 灵圃看护")
            assert herb.code == "IDLE_STARTED", herb.message
        finally:
            await runtime.close()

    asyncio.run(run())
