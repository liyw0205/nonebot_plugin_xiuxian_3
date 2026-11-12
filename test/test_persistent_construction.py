from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import public_project_definitions
from test_wilderness_idle import Clock, change_content, move, send, starter


PROJECTS = ("project.ironwood_bridge", "project.herb_drying_house", "project.basalt_waymarker")


def inventory(runtime):
    with runtime.repository._connect() as connection:
        return json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id='gatherer'").fetchone()[0])


def snapshot_state(runtime):
    with runtime.repository._connect() as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in (
            "players", "operations", "livelihood_projects", "livelihood_project_contributions",
            "livelihood_project_rewards", "player_reputations", "codex_entries", "economy_ledger_entries",
        )}


async def developed(runtime):
    await starter(runtime)
    # Reuse the delivered growth baseline; neither items nor sources are injected.
    with runtime.repository._connect() as connection:
        connection.execute("UPDATE players SET realm_key='qi_gathering', realm_layer=1, stamina=10000, energy=10000")


async def gather(runtime, clock, route, hours, targets):
    for index in range(100):
        if all(inventory(runtime).get(key, 0) >= value for key, value in targets.items()):
            return
        clock.advance(days=1)
        result = await send(runtime, f"开始挂机 {route}", f"{route}-{index}-start")
        assert result.ok, result.message
        clock.advance(hours=hours)
        result = await send(runtime, "领取挂机", f"{route}-{index}-claim")
        assert result.ok and not result.data["fallback"], result.message
    pytest.fail(f"public source {route} did not supply {targets}")


async def transport(runtime, clock, prefix):
    with runtime.repository._connect() as connection:
        location = connection.execute("SELECT location_key FROM players WHERE platform_user_id='gatherer'").fetchone()[0]
    if location == "xuantian.outskirts":
        await move(runtime, clock, "青石镇")
    clock.advance(days=1)
    started = await send(runtime, "开始运输 止血草", prefix + "-start")
    assert started.ok, started.message
    clock.advance(minutes=30)
    settled = await send(runtime, "结算运输", prefix + "-settle")
    assert settled.ok, settled.message
    return settled.operation_id


async def contribute(runtime, clock, key, resource, amount, operation):
    clock.advance(days=1)
    before = inventory(runtime).get(resource, 0)
    result = await send(runtime, f"贡献公共项目 {key} {resource} {amount}", operation)
    assert result.ok, result.message
    assert before - inventory(runtime).get(resource, 0) == result.data["resource_amount"]
    return result


def test_official_three_projects_public_sources_stages_crossweek_effects_and_claims(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await developed(runtime)
            before = snapshot_state(runtime)
            preview = await send(runtime, "工程预览")
            assert len(preview.data["projects"]) == 3 and len(preview.actions) == 1
            assert (await send(runtime, "我的工程")).data["projects"] == []
            assert snapshot_state(runtime) == before
            await move(runtime, clock, "百草坡")
            await gather(runtime, clock, "百草坡采药", 4, {"item.herb.blood_grass": 70})
            await move(runtime, clock, "近郊")
            await move(runtime, clock, "铁木林")
            await gather(runtime, clock, "铁木林拾材", 6, {"item.mat.wood": 60, "item.ore.ironstone": 40})
            await move(runtime, clock, "近郊")
            await move(runtime, clock, "玄武岩径")
            await gather(runtime, clock, "玄武岩径筛砂", 8, {"item.mat.array_sand": 40, "item.ore.ironstone": 100})
            await move(runtime, clock, "近郊")
            await move(runtime, clock, "青石镇")
            await move(runtime, clock, "灵泉谷")
            for index in range(100):
                if inventory(runtime).get("item.herb.spirit_leaf", 0) >= 40:
                    break
                clock.advance(days=1)
                assert (await send(runtime, "开始探索 灵泉采集", f"spring-{index}")).ok
                clock.advance(minutes=3)
                assert (await send(runtime, "结算探索", f"spring-settle-{index}")).ok
            assert inventory(runtime).get("item.herb.spirit_leaf", 0) >= 40
            await move(runtime, clock, "青石镇")
            definitions = public_project_definitions()
            for key in PROJECTS:
                definition = definitions[key]
                for phase_index, phase in enumerate(definition.stages):
                    for resource, target in phase["requirements"].items():
                        previous = definition.stages[phase_index-1]["requirements"].get(resource, 0) if phase_index else 0
                        for chunk_index, amount in enumerate(range(0, target-previous, 30)):
                            await contribute(runtime, clock, key, resource, min(30, target-previous-amount), f"{key}-{phase_index}-{resource}-{chunk_index}")
                    status = await send(runtime, "我的工程")
                    project = next(p for p in status.data["projects"] if p["project_key"] == key)
                    assert project["status"] == "proposed"
                    before = snapshot_state(runtime)
                    denied = await send(runtime, f"贡献公共项目 {key} {next(iter(phase['requirements']))} 1", f"{key}-phase-denied-{phase_index}")
                    assert denied.code == "PROJECT_PHASE_REQUIREMENT" and denied.data["subject"] == phase["name"]
                    assert snapshot_state(runtime) == before
                    source = await transport(runtime, clock, f"{key}-transport-{phase_index}")
                    result = await send(runtime, f"贡献公共项目 {key} 运输 {source}", f"{key}-service-{phase_index}")
                    assert result.ok, result.message
                    assert phase["complete_text"] in result.message
                    if phase_index == 0:
                        await runtime.close()
                        clock.advance(days=8)
                        runtime = create_runtime(data_dir=tmp_path, clock=clock)
                assert result.data["status"] == "active" and result.data["project_contribution_points"] == 140
                current = next(p for p in (await send(runtime, "我的工程")).data["projects"] if p["project_key"] == key)
                assert current["claimable"] and current["business_week"] == "persistent"
                project_id = current["project_id"]
                with runtime.repository._connect() as connection:
                    assert runtime.repository._public_project_effect_values(connection, clock())[definition.effect_key] == definition.effect_value
                if key == PROJECTS[0]:
                    commissions = await send(runtime, "城镇委托")
                    assert {p["stock_total"] for p in commissions.data["commissions"]} == {250, 187, 150}
                elif key == PROJECTS[1]:
                    await send(runtime, "城镇委托")
                    with runtime.repository._connect() as connection:
                        rows = connection.execute("SELECT commission_key, snapshot_json FROM town_commissions WHERE business_date=?", (clock().date().isoformat(),)).fetchall()
                    herb = next(json.loads(row[1]) for row in rows if row[0] == "town_commission.herb_supply")
                    assert herb["reward_stones"] == 20
                else:
                    source = await transport(runtime, clock, "marker-effect")
                    with runtime.repository._connect() as connection:
                        frozen_route = json.loads(connection.execute("SELECT snapshot_json FROM livelihood_trade_routes WHERE settle_operation_id=?", (source,)).fetchone()[0])
                    assert frozen_route["delay_chance_bp"] == 0
                claim = await send(runtime, f"结算公共项目 {project_id}", f"{key}-claim")
                assert claim.ok and claim.data["rewarded"], claim.message
                assert claim.data["reward"] == {"spirit_stones": 40, definition.reward["item"]: 1}
                before = snapshot_state(runtime)
                replay = await send(runtime, f"结算公共项目 {project_id}", f"{key}-claim")
                assert replay.data["idempotent_replay"] and replay.message == claim.message
                assert snapshot_state(runtime) == before
                if definition.reward["item"] == "item.food.spirit_rice":
                    with runtime.repository._connect() as connection:
                        connection.execute("UPDATE players SET stamina=1")
                    food_before = inventory(runtime).get("item.food.spirit_rice", 0)
                    used = await send(runtime, "使用 灵米饭 体力", key + "-food")
                    assert used.ok and inventory(runtime).get("item.food.spirit_rice", 0) == food_before-1, used.message
                    with runtime.repository._connect() as connection:
                        connection.execute("UPDATE players SET stamina=10000")
                clock.advance(days=8)
                current = next(p for p in (await send(runtime, "我的工程")).data["projects"] if p["project_key"] == key)
                assert current["status"] == "maintenance_due" and current["rewarded"] and not current["claimable"]
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT count(*) FROM livelihood_projects WHERE business_week='persistent'").fetchone()[0] == 3
                assert connection.execute("SELECT count(*) FROM livelihood_project_rewards WHERE eligible=1").fetchone()[0] == 3
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("damage", ["cycle", "boolean", "decreasing", "final", "extra", "duplicate", "source", "unrelated", "duration", "effect", "labour"])
def test_construction_content_rejects_invalid_stages_sources_and_effects(damage):
    def mutate(records):
        row = records["livelihood", PROJECTS[0]]
        if damage == "cycle": row["cycle"] = "daily"
        elif damage == "boolean": row["stages"][0]["service_points"] = True
        elif damage == "decreasing": row["stages"][1]["requirements"]["item.mat.wood"] = 1
        elif damage == "final": row["stages"][1]["requirements"].pop("item.mat.wood")
        elif damage == "extra": row["stages"][0]["unused"] = 1
        elif damage == "duplicate": row["stages"][1]["key"] = row["stages"][0]["key"]
        elif damage == "source": row["sources"][0]["exploration_key"] = "explore.missing"
        elif damage == "unrelated": row["sources"][0]["exploration_key"] = "explore.spring_gather"
        elif damage == "duration": row["effect_duration_seconds"] = 0
        elif damage == "effect": row["effect_value"] = 101
        else: row["stages"][0]["service_points"] = 21
    with pytest.raises(ContentError):
        public_project_definitions(change_content(mutate))


def test_construction_qq_help_blue_links_and_plain_text_without_optional_sdk(tmp_path):
    from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text, send_markdown_message

    class Bot:
        async def send(self, event, message, **kwargs):
            self.message = message
            return {"id": "test-reply"}

    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            preview = await send(runtime, "工程预览 铁木便桥", adapter="qq.official")
            assert preview.ok and preview.actions[0].command == "我的工程" and preview.actions[0].enter
            rendered = unquote(_qq_command_links(preview.message, command_prefix="!"))
            assert "!贡献公共项目 铁木便桥 物资 数量" in rendered
            assert "enter=false" in rendered and "mqqapi:" in rendered
            plain = markdown_to_text(preview.message)
            assert "铁木便桥" in plain and "木材" in plain and "开始探索" in plain
            assert "command:" not in plain and "mqqapi:" not in plain
            bot = Bot()
            result = await send_markdown_message(bot, object(), preview.message, actions=preview.actions)
            assert result.sent_format == "text" and "可发送：我的工程" in bot.message
            for adapter in ("qq.official", "onebot.v11"):
                for category in ("生活", "探索"):
                    help_result = await send(runtime, f"修仙帮助 {category}", adapter=adapter)
                    assert "工程预览" in unquote(help_result.message) and "我的工程" in help_result.message
                    assert not help_result.actions
        finally:
            await runtime.close()
    asyncio.run(run())


def compact_content():
    def mutate(records):
        row = records["livelihood", PROJECTS[0]]
        row["requirements"] = {key: 2 for key in row["requirements"]}
        row["stages"][0]["requirements"] = {"item.mat.wood": 1}
        row["stages"][1]["requirements"] = dict(row["requirements"])
    return change_content(mutate)


async def unit_ready(runtime):
    await developed(runtime)
    runtime.repository.content = compact_content()
    # Small isolated transaction fixtures, not evidence of public item provenance.
    with runtime.repository._connect() as connection:
        connection.execute("UPDATE players SET location_key='xuantian.new_town', spirit_stones=?, inventory_json=?", (
            str(10**80).encode(), json.dumps({"item.mat.wood": 10, "item.ore.ironstone": 10, "item.herb.blood_grass": 10}),
        ))


async def compact_finish(runtime, clock, *, footed=False, key=PROJECTS[0]):
    if not footed:
        await contribute(runtime, clock, key, "item.mat.wood", 1, "footing")
    source = await transport(runtime, clock, "first-route")
    result = await send(runtime, f"贡献公共项目 {key} 运输 {source}", "first-service")
    assert result.ok, result.message
    await contribute(runtime, clock, key, "item.mat.wood", 1, "deck-wood")
    await contribute(runtime, clock, key, "item.ore.ironstone", 2, "deck-stone")
    source = await transport(runtime, clock, "second-route")
    result = await send(runtime, f"贡献公共项目 {key} 运输 {source}", "second-service")
    assert result.ok and result.data["status"] == "active", result.message
    return result.data["project_id"]


@pytest.mark.parametrize("failure", ["progress", "contribution", "operation"])
def test_phase_contribution_fault_rolls_back_then_retries(failure, tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            table, action = {
                "progress": ("livelihood_projects", "UPDATE"),
                "contribution": ("livelihood_project_contributions", "INSERT"),
                "operation": ("operations", "INSERT"),
            }[failure]
            with runtime.repository._connect() as connection:
                connection.execute(f"CREATE TRIGGER fail_construction BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'injected construction failure'); END")
            before = snapshot_state(runtime)
            result = await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "fault")
            assert result.code == "PERSISTENCE_ERROR" and result.retryable
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_construction")
            result = await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "fault")
            assert result.ok and result.data["resource_amount"] == 1
            before = snapshot_state(runtime)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "fault")).data["idempotent_replay"]
            assert snapshot_state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["reward", "codex", "operation"])
def test_project_reward_fault_rollback_retry_and_huge_currency(failure, tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            project_id = await compact_finish(runtime, clock)
            table = {"reward": "livelihood_project_rewards", "codex": "codex_entries", "operation": "operations"}[failure]
            with runtime.repository._connect() as connection:
                connection.execute(f"CREATE TRIGGER fail_construction BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected construction reward failure'); END")
            before = snapshot_state(runtime)
            result = await send(runtime, f"结算公共项目 {project_id}", "reward-fault")
            assert result.code == "PERSISTENCE_ERROR" and result.retryable
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_construction")
            result = await send(runtime, f"结算公共项目 {project_id}", "reward-fault")
            assert result.ok and result.data["reward"]["spirit_stones"] == 40
            with runtime.repository._connect() as connection:
                value = connection.execute("SELECT spirit_stones FROM players").fetchone()[0]
                assert isinstance(value, bytes) and int(value) >= 10**80 + 40
            before = snapshot_state(runtime)
            result = await send(runtime, f"结算公共项目 {project_id}", "reward-fault")
            assert result.data["idempotent_replay"] and snapshot_state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


def test_closed_project_restart_preserves_stages_and_expired_unclaimed_reward(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            project_id = await compact_finish(runtime, clock)
            await runtime.close()
            clock.advance(days=10)
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            def close(records):
                for key in PROJECTS:
                    records["livelihood", key]["status"] = "locked"
                    records["livelihood", key]["effect_value"] = 99
                    records["livelihood", key]["name"] = "改名后的工程"
            runtime.repository.content = change_content(close)
            before = snapshot_state(runtime)
            status = await send(runtime, "我的工程")
            project = status.data["projects"][0]
            assert project["claimable"] and project["status"] == "maintenance_due"
            assert project["label"] == "铁木便桥" and project["requirements"]["item.mat.wood"] == 2
            assert snapshot_state(runtime) == before
            denied = await send(runtime, f"贡献公共项目 {PROJECTS[1]} 血草 1", "closed-new")
            assert denied.code == "LIVELIHOOD_CONTENT_CLOSED" and snapshot_state(runtime) == before
            result = await send(runtime, f"结算公共项目 {project_id}", "late-reward")
            assert result.ok and result.data["reward"]["spirit_stones"] == 40
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock()) == {}
        finally:
            await runtime.close()
    asyncio.run(run())


def test_bad_phase_snapshot_and_operation_are_zero_write_then_repair(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            result = await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "snapshot-start")
            assert result.ok
            with runtime.repository._connect() as connection:
                original = connection.execute("SELECT snapshot_json FROM livelihood_projects").fetchone()[0]
                bad = json.loads(original)
                bad["stages"][1]["service_points"] = True
                connection.execute("UPDATE livelihood_projects SET snapshot_json=?", (json.dumps(bad),))
            before = snapshot_state(runtime)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "bad-snapshot")).code == "PERSISTENCE_ERROR"
            assert snapshot_state(runtime) == before
            denied = await send(runtime, "结算公共项目 铁木便桥", "bad-settlement-snapshot")
            assert denied.code == "PERSISTENCE_ERROR" and denied.retryable
            assert snapshot_state(runtime) == before
            with pytest.raises(ContentError):
                await send(runtime, "我的工程")
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE livelihood_projects SET snapshot_json=?", (original,))
                receipt = connection.execute("SELECT result_json FROM operations WHERE operation_id='snapshot-start'").fetchone()[0]
                connection.execute("UPDATE operations SET result_json='[]' WHERE operation_id='snapshot-start'")
            before = snapshot_state(runtime)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "snapshot-start")).code == "OPERATION_CONFLICT"
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='snapshot-start'", (receipt,))
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "snapshot-start")).data["idempotent_replay"]
            malformed = json.loads(receipt)
            malformed["project"]["service_points"] = True
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='snapshot-start'", (json.dumps(malformed),))
            before = snapshot_state(runtime)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "snapshot-start")).code == "PERSISTENCE_ERROR"
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='snapshot-start'", (receipt,))
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 木材 1", "snapshot-start")).data["idempotent_replay"]
        finally:
            await runtime.close()
    asyncio.run(run())


def test_frozen_chinese_name_and_alias_survive_close_rename_and_restart(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            definition = public_project_definitions(runtime.repository.content)[PROJECTS[0]]
            alias = definition.aliases[0]
            assert (await send(runtime, "贡献公共项目 铁木便桥 木材 1", "chinese-footing")).ok
            await runtime.close()
            clock.advance(days=8)
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            def close(records):
                row = records["livelihood", PROJECTS[0]]
                row.update(status="locked", name="改名后的工程", aliases=[], stages=[])
            runtime.repository.content = change_content(close)
            project_id = await compact_finish(runtime, clock, footed=True, key=alias)
            status = (await send(runtime, "我的工程")).data["projects"][0]
            assert status["project_id"] == project_id and status["label"] == "铁木便桥"
            claim = await send(runtime, "结算公共项目 铁木便桥", "chinese-reward")
            assert claim.ok and "铁木便桥" in claim.message
            before = snapshot_state(runtime)
            replay = await send(runtime, f"结算公共项目 {alias}", "chinese-reward")
            assert replay.data["idempotent_replay"] and replay.message == claim.message
            assert snapshot_state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("field", ["target_points", "contribution_points", "resource_amount", "quantity"])
def test_malformed_construction_receipt_numbers_refuse_zero_write_then_repair(field, tmp_path):
    async def run():
        runtime = create_runtime(data_dir=tmp_path, clock=Clock())
        try:
            await unit_ready(runtime)
            command = "贡献公共项目 铁木便桥 木材 1"
            assert (await send(runtime, command, "receipt-number")).ok
            with runtime.repository._connect() as connection:
                original = connection.execute("SELECT result_json FROM operations WHERE operation_id='receipt-number'").fetchone()[0]
                receipt = json.loads(original)
                if field == "target_points":
                    receipt["project"][field] += 1
                else:
                    receipt[field] = True
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='receipt-number'", (json.dumps(receipt),))
            before = snapshot_state(runtime)
            denied = await send(runtime, command, "receipt-number")
            assert denied.code == "PERSISTENCE_ERROR" and denied.retryable
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='receipt-number'", (original,))
            before = snapshot_state(runtime)
            assert (await send(runtime, command, "receipt-number")).data["idempotent_replay"]
            assert snapshot_state(runtime) == before
        finally:
            await runtime.close()
    asyncio.run(run())


def test_two_runtimes_concurrent_contribution_and_reward_do_not_double_write(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        other = None
        try:
            await unit_ready(runtime)
            other = create_runtime(data_dir=tmp_path, clock=clock)
            other.repository.content = compact_content()
            results = await asyncio.gather(*(send(r, f"贡献公共项目 {PROJECTS[0]} 木材 1", "racing-contribution") for r in (runtime, other)))
            assert all(result.ok for result in results)
            assert sorted(result.data["idempotent_replay"] for result in results) == [False, True]
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT count(*) FROM livelihood_project_contributions").fetchone()[0] == 1
            project_id = await compact_finish(runtime, clock, footed=True)
            results = await asyncio.gather(*(send(r, f"结算公共项目 {project_id}", "racing-reward") for r in (runtime, other)))
            assert all(result.ok for result in results)
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT count(*) FROM livelihood_project_rewards").fetchone()[0] == 1
        finally:
            if other is not None:
                await other.close()
            await runtime.close()
    asyncio.run(run())


def test_completed_effects_use_frozen_strength_maximum_and_expiry(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            await compact_finish(runtime, clock)
            with runtime.repository._connect() as connection:
                legacy = runtime.repository._ensure_project(connection, runtime.repository._business_week(clock()), clock(), "project.town_well")
                snapshot = json.loads(legacy["snapshot_json"])
                for field in ("cycle", "stages", "sources", "effect_value", "effect_duration_seconds", "daily_limit", "selectors"):
                    snapshot.pop(field, None)
                connection.execute("UPDATE livelihood_projects SET snapshot_json=?, status='active', effect_starts_at=?, effect_ends_at=? WHERE id=?", (
                    json.dumps(snapshot), clock().isoformat(), (clock() + timedelta(days=14)).isoformat(), legacy["id"],
                ))
            before = snapshot_state(runtime)
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock())["town_commission.stock_bonus"] == 25
            assert snapshot_state(runtime) == before
            def changed(records):
                records["livelihood", PROJECTS[0]]["effect_value"] = 90
            runtime.repository.content = change_content(changed)
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock())["town_commission.stock_bonus"] == 25
            clock.advance(days=7)
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock())["town_commission.stock_bonus"] == 20
            clock.advance(days=7)
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock()) == {}
        finally:
            await runtime.close()
    asyncio.run(run())


def test_failed_transport_is_not_labour_and_does_not_open_project(tmp_path):
    from nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_rules import choose_route_event, route_definitions

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            definition = route_definitions()["route.town_ironwood_grove"]
            operation = next(f"construction-failed-route-{index}" for index in range(100) if choose_route_event(definition.events, f"construction-failed-route-{index}")[0].outcome == "failed")
            started = await send(runtime, "开始运输 铁木行商 木材 1", operation)
            assert started.ok, started.message
            clock.advance(hours=1)
            settled = await send(runtime, "结算运输", "failed-source")
            assert settled.ok and settled.data["event_outcome"] == "failed"
            before = snapshot_state(runtime)
            result = await send(runtime, "贡献公共项目 铁木便桥 运输 failed-source", "failed-labour")
            assert result.code == "PROJECT_PHASE_REQUIREMENT" and result.data["reason"] == "transport_not_successful"
            assert snapshot_state(runtime) == before
            assert (await send(runtime, "我的工程")).data["projects"] == []
        finally:
            await runtime.close()
    asyncio.run(run())


def test_open_phase_closed_content_uses_original_snapshot_and_successful_owned_labour(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            await contribute(runtime, clock, PROJECTS[0], "item.mat.wood", 1, "footing")
            def close(records):
                records["livelihood", PROJECTS[0]]["status"] = "locked"
                records["livelihood", PROJECTS[0]]["stages"] = []
                records["livelihood", PROJECTS[0]]["effect_value"] = 99
            runtime.repository.content = change_content(close)
            project_id = await compact_finish(runtime, clock, footed=True)
            status = (await send(runtime, "我的工程")).data["projects"][0]
            assert status["requirements"] == {"item.mat.wood": 2, "item.ore.ironstone": 2}
            assert len(status["stages"]) == 2
            with runtime.repository._connect() as connection:
                assert runtime.repository._public_project_effect_values(connection, clock())["town_commission.stock_bonus"] == 25
            assert (await send(runtime, f"结算公共项目 {project_id}", "closed-claim")).ok
        finally:
            await runtime.close()
    asyncio.run(run())


def test_labour_quota_duplicate_owner_and_changed_receipt_are_zero_write(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            source = await transport(runtime, clock, "quota-route")
            command = f"贡献公共项目 {PROJECTS[0]} 运输 {source}"
            result = await send(runtime, command, "labour-first")
            assert result.ok, result.message
            before = snapshot_state(runtime)
            assert (await send(runtime, command, "labour-second")).code == "PROJECT_SOURCE_ALREADY_USED"
            assert (await send(runtime, command, "labour-first", user="intruder")).code == "OPERATION_CONFLICT"
            assert snapshot_state(runtime) == before
            source2 = await transport(runtime, clock, "surplus-route")
            before = snapshot_state(runtime)
            result = await send(runtime, f"贡献公共项目 {PROJECTS[0]} 运输 {source2}", "surplus-service")
            assert result.code == "PROJECT_PHASE_REQUIREMENT" and result.data["reason"] == "phase_labour_complete"
            assert snapshot_state(runtime) == before
            await contribute(runtime, clock, PROJECTS[0], "item.mat.wood", 1, "finish-phase")
            with runtime.repository._connect() as connection:
                original = connection.execute("SELECT result_json FROM operations WHERE operation_id=?", (source2,)).fetchone()[0]
                broken = json.loads(original)
                broken["reward_stones"] += 1
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (json.dumps(broken), source2))
            before = snapshot_state(runtime)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 运输 {source2}", "changed-receipt")).code == "PROJECT_SOURCE_INVALID"
            assert snapshot_state(runtime) == before
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (original, source2))
                connection.execute("UPDATE livelihood_project_contributions SET created_at=?", (clock().isoformat(),))
            before = snapshot_state(runtime)
            result = await send(runtime, f"贡献公共项目 {PROJECTS[0]} 运输 {source2}", "quota-denied")
            assert result.code == "PROJECT_CONTRIBUTION_LIMIT" and snapshot_state(runtime) == before
            clock.advance(days=1)
            assert (await send(runtime, f"贡献公共项目 {PROJECTS[0]} 运输 {source2}", "quota-denied")).ok
        finally:
            await runtime.close()
    asyncio.run(run())


def test_herb_project_reward_is_actual_seed_consumed_by_field(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await unit_ready(runtime)
            key = PROJECTS[1]
            def compact(records):
                row = records["livelihood", key]
                row["requirements"] = {"item.herb.blood_grass": 2, "item.herb.spirit_leaf": 2}
                row["stages"][0]["requirements"] = {"item.herb.blood_grass": 1}
                row["stages"][1]["requirements"] = dict(row["requirements"])
            runtime.repository.content = change_content(compact)
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET inventory_json=?", (json.dumps({"item.herb.blood_grass": 4, "item.herb.spirit_leaf": 2}),))
            await contribute(runtime, clock, key, "item.herb.blood_grass", 1, "herb-first")
            source = await transport(runtime, clock, "herb-transport-first")
            assert (await send(runtime, f"贡献公共项目 {key} 运输 {source}", "herb-service-first")).ok
            await contribute(runtime, clock, key, "item.herb.blood_grass", 1, "herb-last")
            await contribute(runtime, clock, key, "item.herb.spirit_leaf", 2, "leaf-last")
            source = await transport(runtime, clock, "herb-transport-last")
            result = await send(runtime, f"贡献公共项目 {key} 运输 {source}", "herb-service-last")
            assert result.ok and result.data["status"] == "active"
            assert inventory(runtime).get("item.herb.blood_grass", 0) == 0
            claim = await send(runtime, f"结算公共项目 {result.data['project_id']}", "herb-project-claim")
            assert claim.ok and claim.data["reward"]["item.herb.blood_grass"] == 1
            assert inventory(runtime)["item.herb.blood_grass"] == 1
            await move(runtime, clock, "青石镇")
            assert (await send(runtime, "租住居所 客房", "seed-room")).ok
            planted = await send(runtime, "灵田播种 止血草", "reward-seed")
            assert planted.ok, planted.message
            assert inventory(runtime).get("item.herb.blood_grass", 0) == 0
            assert (await send(runtime, "灵田维护", "reward-seed-tend")).ok
            clock.advance(hours=4)
            harvested = await send(runtime, "灵田收获", "reward-seed-harvest")
            assert harvested.ok and inventory(runtime).get("item.herb.blood_grass", 0) >= 3, harvested.message
        finally:
            await runtime.close()
    asyncio.run(run())
