from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='dao_union', realm_layer=1, location_key='dao.origin_gate', "
            "stamina=100, stamina_max=100, intro_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"flags": ["access.final_heaven"]}), adapter, user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        season_id = final_heaven_season_window(runtime.repository._now())[0]
        now_text = runtime.repository._now().isoformat()
        connection.execute(
            "INSERT INTO dao_origin_qualifications("
            "player_id, season_id, readiness_flag, status, snapshot_json, operation_id, created_at, updated_at) "
            "VALUES (?, ?, 'access.final_heaven', 'qualified', ?, ?, ?, ?)",
            (
                player_id,
                season_id,
                json.dumps({"season_id": season_id, "readiness_flag": "access.final_heaven"}),
                f"{user}:qualification",
                now_text,
                now_text,
            ),
        )


async def _run(runtime, adapter: str, user: str, prefix: str, *, already_entered: bool = False):
    entered = None
    if not already_entered:
        entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:enter"), "进入秘境 道源秘境")
        assert entered.code == "DAO_ORIGIN_ENTERED", entered
    for index, node in enumerate(("道源关隘", "道源泉眼", "三界校验印", "服务档案库", "道果痕迹", "见证台", "道源誓约", "新章门扉")):
        result = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:node:{index}"), f"选择秘境节点 {node}")
        assert result.ok, result
    settled = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:settle"), "结算秘境")
    assert settled.code == "DAO_ORIGIN_SETTLED", settled
    return entered, settled


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_dao_origin_full_route_is_idempotent_and_resource_isolated(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"dao-origin-{adapter}"
            await _player(runtime, adapter, user)
            preview = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "preview"), "秘境预览")
            assert any(item["instance_key"] == "instance.secret_realm.dao_origin" for item in preview.data["realms"])
            entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入秘境 道源秘境")
            assert entered.ok
            replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入秘境 道源秘境")
            assert replay.data["idempotent_replay"] is True
            skipped = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "skip"), "选择秘境节点 道源泉眼")
            assert skipped.code == "DAO_ORIGIN_NODE_FORBIDDEN"
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            _, settled = await _run(runtime, adapter, user, "resume", already_entered=True)
            replay_settlement = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "resume:settle"), "结算秘境")
            assert replay_settlement.data["idempotent_replay"] is True
            quota = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "quota"), "进入秘境 道源秘境")
            assert quota.code == "DAO_ORIGIN_QUOTA_EXHAUSTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, intro_json, dao_progress, merit, codex_count = connection.execute(
                    "SELECT p.stamina, p.intro_json, p.dao_fruit_progress, p.ascension_merit, "
                    "(SELECT COUNT(*) FROM codex_entries c WHERE c.player_id=p.id AND c.entry_key='codex.dao.service_origin') "
                    "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert stamina == 40
            assert json.loads(intro_json)["flags"].count("story.dao_origin") == 1
            assert codex_count == 1
            assert dao_progress == 0
            assert merit == 0
            assert settled.data["story_flag_written"] is True
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_rejects_stale_season_qualification() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            user = "stale-dao-origin"
            created = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "create"), "开始修仙"
            )
            assert created.ok
            season_id, season_start, _ = final_heaven_season_window(clock())
            old_season = final_heaven_season_window(season_start - timedelta(seconds=1))[0]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    ("qq.official", user),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET realm_key='dao_union', realm_layer=1, location_key='dao.origin_gate', "
                    "stamina=100, stamina_max=100, intro_json=? WHERE id=?",
                    (json.dumps({"flags": ["access.final_heaven"]}), player_id),
                )
                connection.execute(
                    "INSERT INTO dao_origin_qualifications("
                    "player_id, season_id, readiness_flag, status, snapshot_json, operation_id, created_at, updated_at) "
                    "VALUES (?, ?, 'access.final_heaven', 'qualified', ?, ?, ?, ?)",
                    (
                        player_id,
                        old_season,
                        json.dumps({"season_id": old_season, "readiness_flag": "access.final_heaven"}),
                        f"{user}:old-qualification",
                        season_start.isoformat(),
                        season_start.isoformat(),
                    ),
                )
            result = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "enter"), "进入秘境 道源秘境"
            )
            assert result.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM dao_origin_runs WHERE player_id=?", (player_id,)
                ).fetchone()[0] == 0
            assert season_id != old_season
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_rejects_malformed_current_qualification_snapshot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            user = "malformed-dao-origin"
            created = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "create"), "开始修仙"
            )
            assert created.ok
            season_id = final_heaven_season_window(clock())[0]
            now_text = clock().isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    ("qq.official", user),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET realm_key='dao_union', realm_layer=1, location_key='dao.origin_gate', "
                    "stamina=100, stamina_max=100, intro_json=? WHERE id=?",
                    (json.dumps({"flags": ["access.final_heaven"]}), player_id),
                )
                connection.execute(
                    "INSERT INTO dao_origin_qualifications("
                    "player_id, season_id, readiness_flag, status, snapshot_json, operation_id, created_at, updated_at) "
                    "VALUES (?, ?, 'access.final_heaven', 'qualified', '{bad', ?, ?, ?)",
                    (player_id, season_id, f"{user}:malformed", now_text, now_text),
                )
            result = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "enter"), "进入秘境 道源秘境"
            )
            assert result.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM dao_origin_runs WHERE player_id=?", (player_id,)
                ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_rejects_legacy_permission_flag() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", "legacy-dao-origin", "create"), "开始修仙"
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='dao_union', realm_layer=1, location_key='dao.origin_gate', "
                    "stamina=100, stamina_max=100, intro_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"flags": ["access.dao.origin"]}), "qq.official", "legacy-dao-origin"),
                )
            result = await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "legacy-dao-origin", "enter"),
                "进入秘境 道源秘境",
            )
            assert result.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_mixed_adapter_resume_expiry_and_system_compensation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "dao-origin-handoff"
            await _player(runtime, "qq.official", user)
            entered = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "handoff:enter"), "进入秘境 道源秘境")
            assert entered.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET platform='onebot.v11' WHERE platform='qq.official' AND platform_user_id=?", (user,))
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for index, node in enumerate(("道源关隘", "道源泉眼")):
                result = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, f"handoff:{index}"), f"选择秘境节点 {node}")
                assert result.ok, result
            clock.advance(hours=1, seconds=1)
            expired = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:expire"), "结算秘境")
            assert expired.code == "DAO_ORIGIN_SETTLED"
            assert expired.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute("SELECT stamina FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)).fetchone()[0]
            assert stamina == 40

            user2 = "dao-origin-compensation"
            await _player(runtime, "qq.official", user2)
            entered2 = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user2, "comp:enter"), "进入秘境 道源秘境")
            compensated = await runtime.repository.compensate_dao_origin_system_failure(run_id=entered2.data["run_id"], operation_id="comp:abort")
            assert compensated.outcome == "system_aborted"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina2 = connection.execute("SELECT stamina FROM players WHERE platform='qq.official' AND platform_user_id=?", (user2,)).fetchone()[0]
            assert stamina2 == 100
            await runtime.close()

    asyncio.run(run())
