from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, days: int = 0) -> None:
        from datetime import timedelta

        self.value += timedelta(days=days)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def test_public_project_contribution_is_atomic_capped_and_rewarded_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)))
            context = _context("project-user")
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(context, "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", ("project-user",)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET inventory_json = ? WHERE id = ?",
                    (json.dumps({"item.mat.wood": 100}), player_id),
                )
            project_key = "project.town_well"
            contribution = await runtime.dispatch(
                replace(context, operation_id="project-too-large"),
                f"贡献公共项目 {project_key} 31",
            )
            assert contribution.code == "PROJECT_CONTRIBUTION_LIMIT"
            contribution = await runtime.dispatch(
                replace(context, operation_id="project-contribution"),
                f"贡献公共项目 {project_key} 10",
            )
            assert contribution.code == "PROJECT_CONTRIBUTED"
            replay = await runtime.dispatch(
                replace(context, operation_id="project-contribution"),
                f"贡献公共项目 {project_key} 10",
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                wood = json.loads(connection.execute("SELECT inventory_json FROM players WHERE id = ?", (player_id,)).fetchone()[0])
                assert wood.get("item.mat.wood", 0) == 90
            await runtime.close()

    asyncio.run(run())


def test_public_project_completion_and_personal_reward_do_not_change_cultivation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)))
            context = _context("project-complete")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id = ?", ("project-complete",)).fetchone()[0]
                connection.execute("UPDATE players SET inventory_json = ?, spirit_stones = 100 WHERE id = ?", (json.dumps({"item.mat.wood": 100}), player_id))
            key = "project.town_well"
            for index in range(3):
                result = await runtime.dispatch(replace(context, operation_id=f"project-part-{index}"), f"贡献公共项目 {key} 木材 30")
                assert result.ok
            result = await runtime.dispatch(replace(context, operation_id="project-last"), f"贡献公共项目 {key} 木材 10")
            assert result.data["status"] == "active"
            settled = await runtime.dispatch(replace(context, operation_id="project-settle"), "结算公共项目")
            assert settled.code == "PROJECT_SETTLED"
            assert settled.data["reward"]["spirit_stones"] == 30
            replay = await runtime.dispatch(replace(context, operation_id="project-settle"), "结算公共项目")
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT spirit_stones, cultivation, total_cultivation FROM players WHERE id = ?", (player_id,)).fetchone()
                assert row == (130, 0, 0)
                assert connection.execute("SELECT COUNT(*) FROM livelihood_project_rewards WHERE player_id = ?", (player_id,)).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_public_project_concurrent_same_operation_deducts_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)))
            context = _context("project-concurrent")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id = ?", ("project-concurrent",)).fetchone()[0]
                connection.execute("UPDATE players SET inventory_json = ? WHERE id = ?", (json.dumps({"item.mat.wood": 30}), player_id))
            project = {"project_key": "project.town_well"}
            operation = replace(context, operation_id="project-concurrent-op")
            results = await asyncio.gather(
                runtime.dispatch(operation, f"贡献公共项目 {project['project_key']} 30"),
                runtime.dispatch(operation, f"贡献公共项目 {project['project_key']} 30"),
            )
            assert all(result.ok for result in results)
            assert sum(result.data["idempotent_replay"] is False for result in results) == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE id = ?", (player_id,)).fetchone()[0])
                assert inventory == {}
                assert connection.execute("SELECT COUNT(*) FROM livelihood_project_contributions").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_public_project_resource_failure_leaves_player_and_progress_unchanged() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)))
            context = _context("project-insufficient")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            before = await runtime.dispatch(context, "公共项目")
            failed = await runtime.dispatch(
                replace(context, operation_id="project-insufficient-op"),
                "贡献公共项目 project.town_well 木材 10",
            )
            assert failed.code == "RESOURCE_INSUFFICIENT"
            after = await runtime.dispatch(context, "公共项目")
            assert after.data["projects"][0]["progress"] == before.data["projects"][0]["progress"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?",
                    ("project-insufficient",),
                ).fetchone()
                assert row[0] == 100
                assert json.loads(row[1]) == {"item.food.coarse_spirit_rice": 3, "item.herb.blood_grass": 3}
                assert connection.execute("SELECT COUNT(*) FROM livelihood_project_contributions").fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_completed_public_projects_apply_their_fixed_effect_snapshots() -> None:
    async def complete(runtime, context, key: str, resource: str, contributions: tuple[int, ...]) -> None:
        for index, amount in enumerate(contributions):
            result = await runtime.dispatch(
                replace(context, operation_id=f"{key}-{resource}-{index}"),
                f"贡献公共项目 {key} {resource} {amount}",
            )
            assert result.ok, result

    async def town_well() -> None:
        clock = MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            context = _context("well-effect")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id = ?", ("well-effect",)).fetchone()[0]
                connection.execute("UPDATE players SET inventory_json = ? WHERE id = ?", (json.dumps({"item.mat.wood": 100}), player_id))
            before = await runtime.dispatch(context, "城镇委托")
            assert {item["stock_total"] for item in before.data["commissions"]} == {200, 150, 120}
            await complete(runtime, context, "project.town_well", "木材", (30, 30, 30, 10))
            same_day = await runtime.dispatch(context, "城镇委托")
            assert {item["stock_total"] for item in same_day.data["commissions"]} == {240, 180, 144}
            clock.advance(days=1)
            commissions = await runtime.dispatch(context, "城镇委托")
            assert {item["stock_total"] for item in commissions.data["commissions"]} == {240, 180, 144}
            await runtime.close()

    async def herb_garden() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            context = _context("garden-effect")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id = ?", ("garden-effect",)).fetchone()[0]
                connection.execute("UPDATE players SET inventory_json = ? WHERE id = ?", (json.dumps({"item.herb.spirit_leaf": 120}), player_id))
            await complete(runtime, context, "project.herb_garden", "灵叶", (30, 30, 30, 30))
            clock.advance(days=1)
            commissions = await runtime.dispatch(context, "城镇委托")
            herb = next(item for item in commissions.data["commissions"] if item["commission_key"] == "town_commission.herb_supply")
            assert herb["stock_total"] == 200
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute("SELECT snapshot_json FROM town_commissions WHERE commission_id = ?", (herb["commission_id"],)).fetchone()[0])
                assert snapshot["reward_stones"] == 19
            await runtime.close()

    async def market_road() -> None:
        clock = MutableClock(datetime(2026, 9, 21, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            context = _context("road-effect")
            await runtime.dispatch(context, "开始修仙")
            await runtime.dispatch(context, "寻仙问道")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id = ?", ("road-effect",)).fetchone()[0]
                connection.execute(
                    "UPDATE players SET spirit_stones = 3000, inventory_json = ? WHERE id = ?",
                    (json.dumps({"item.material.cloud_iron": 60, "item.herb.blood_grass": 1}), player_id),
                )
            await complete(runtime, context, "project.market_road", "云铁", (30, 30))
            await complete(runtime, context, "project.market_road", "灵石", (30, 30))
            started = await runtime.dispatch(replace(context, operation_id="road-effect-route"), "开始运输 止血草")
            assert started.code == "ROUTE_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute("SELECT snapshot_json FROM livelihood_trade_routes WHERE route_id = ?", (started.data["route_id"],)).fetchone()[0])
                assert snapshot["delay_chance_bp"] == 0
            await runtime.close()

    asyncio.run(town_well())
    asyncio.run(herb_garden())
    asyncio.run(market_road())


def test_public_project_codex_discovery_freezes_content_and_replays_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "content"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
                runtime = create_runtime(
                    data_dir=data_dir,
                    clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)),
                )
                user = f"project-codex-{adapter}"
                context = CommandContext(adapter=adapter, user_id=user, operation_id=f"{user}:base")
                assert (await runtime.dispatch(context, "开始修仙")).ok
                assert (await runtime.dispatch(replace(context, operation_id=f"{user}:seeking"), "寻仙问道")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET inventory_json = ? WHERE id = ?",
                        (json.dumps({"item.mat.wood": 100}), player_id),
                    )
                for index, amount in enumerate((30, 30, 30, 10)):
                    contributed = await runtime.dispatch(
                        replace(context, operation_id=f"{user}:contribute:{index}"),
                        f"贡献公共项目 project.town_well 木材 {amount}",
                    )
                    assert contributed.code == "PROJECT_CONTRIBUTED"
                operation_id = f"{user}:settle"
                settled = await runtime.dispatch(
                    replace(context, operation_id=operation_id),
                    "结算公共项目",
                )
                assert settled.code == "PROJECT_SETTLED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT category, first_seen_operation_id, payload_json FROM codex_entries "
                        "WHERE player_id = ? AND entry_key = ?",
                        (player_id, "codex.dao.service_public_works"),
                    ).fetchone()
                    assert row is not None
                    assert row[0] == "service"
                    assert row[1] == operation_id
                    assert json.loads(row[2])["label"] == "道统公共建设"
                await runtime.close()

                entries_path = data_dir / "图鉴" / "条目.json"
                entries = json.loads(entries_path.read_text(encoding="utf-8"))
                entry = next(
                    item for item in entries["records"] if item["key"] == "codex.dao.service_public_works"
                )
                entry["name"] = "改名后的道统公共建设"
                entry["status"] = "closed"
                entries_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

                recovered = create_runtime(data_dir=data_dir)
                replay = await recovered.dispatch(
                    replace(context, operation_id=operation_id),
                    "结算公共项目",
                )
                assert replay.code == "PROJECT_SETTLED"
                assert replay.data["idempotent_replay"] is True
                overview = await recovered.dispatch(
                    replace(context, operation_id=f"{user}:codex"),
                    "我的图鉴 服务",
                )
                assert overview.code == "CODEX_OVERVIEW"
                assert any(
                    item["entry_key"] == "codex.dao.service_public_works"
                    and item["label"] == "道统公共建设"
                    for item in overview.data["entries"]
                )
                await recovered.close()

    asyncio.run(run())


def test_public_project_codex_failure_rolls_back_reward_and_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = create_runtime(
                data_dir=temp_dir,
                clock=MutableClock(datetime(2026, 10, 12, tzinfo=timezone.utc)),
            )
            adapter, user = "qq.official", "project-codex-failure"
            context = CommandContext(adapter=adapter, user_id=user, operation_id=f"{user}:base")
            assert (await runtime.dispatch(context, "开始修仙")).ok
            assert (await runtime.dispatch(replace(context, operation_id=f"{user}:seeking"), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET inventory_json = ?, spirit_stones = 100 WHERE id = ?",
                    (json.dumps({"item.mat.wood": 100}), player_id),
                )
            for index, amount in enumerate((30, 30, 30, 10)):
                result = await runtime.dispatch(
                    replace(context, operation_id=f"{user}:contribute:{index}"),
                    f"贡献公共项目 project.town_well 木材 {amount}",
                )
                assert result.ok
            operation_id = f"{user}:settle"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_project_codex
                    BEFORE INSERT ON codex_entries
                    WHEN NEW.entry_key = 'codex.dao.service_public_works'
                    BEGIN SELECT RAISE(ABORT, 'injected project codex failure'); END
                    """
                )
            failed = await runtime.dispatch(
                replace(context, operation_id=operation_id),
                "结算公共项目",
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE id = ?",
                    (player_id,),
                ).fetchone()
                assert state[0] == 100
                assert json.loads(state[1]).get("item.mat.wood", 0) == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM livelihood_project_rewards WHERE player_id = ?", (player_id,)
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id = ? AND entry_key = ?",
                    (player_id, "codex.dao.service_public_works"),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = ?", (operation_id,)
                ).fetchone()[0] == 0
                connection.execute("DROP TRIGGER fail_project_codex")
            retried = await runtime.dispatch(
                replace(context, operation_id=operation_id),
                "结算公共项目",
            )
            assert retried.code == "PROJECT_SETTLED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id = ? AND entry_key = ?",
                    (player_id, "codex.dao.service_public_works"),
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
