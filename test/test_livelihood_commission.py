from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import town_commission_definitions


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 22, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def _content(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    return data_dir


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("before", [3, 6])
def test_commission_snapshot_survives_content_change_restart_and_conflict(
    tmp_path: Path, adapter: str, before: int,
) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        clock = MutableClock()
        location_file = data_dir / "地图" / "地点.json"
        locations = json.loads(location_file.read_text(encoding="utf-8"))
        town = next(row for row in locations["records"] if row["key"] == "xuantian.new_town")
        town["local_reputation_maximum"] = 4
        location_file.write_text(json.dumps(locations, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        base = CommandContext(adapter=adapter, user_id="commission-recovery")

        async def send(operation: str, text: str):
            return await runtime.adapters.dispatch(
                adapter, replace(base, operation_id=operation), text
            )

        assert (await send("create", "开始修仙")).ok
        assert (await send("seek", "寻仙问道")).ok
        listing = await send("list", "城镇委托")
        assert listing.code == "COMMISSION_LIST"
        assert "止血草" in listing.message
        assert "town_commission." not in listing.message
        assert "item." not in listing.message
        assert "published" not in listing.message
        accepted = await send("accept", "接取委托 止血草供应")
        assert accepted.code == "COMMISSION_ACCEPTED"
        assert "item." not in accepted.message
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, base.user_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, ?, 100, ?)",
                (player_id, json.dumps({"local.xuantian.new_town": before}), clock.value.isoformat()),
            )
            snapshot = json.loads(connection.execute(
                "SELECT snapshot_json FROM town_commission_claims WHERE claim_id=?",
                (accepted.data["claim_id"],),
            ).fetchone()[0])
        assert snapshot["local_reputation_maximum"] == 4
        assert snapshot["reward_stones"] == 18
        await runtime.close()

        town["local_reputation_maximum"] = 8
        location_file.write_text(json.dumps(locations, ensure_ascii=False), encoding="utf-8")
        commission_file = data_dir / "生活" / "生活.json"
        commissions = json.loads(commission_file.read_text(encoding="utf-8"))
        herb = next(row for row in commissions["records"] if row["key"] == "town_commission.herb_supply")
        herb["reward"]["amount"] = 52
        herb["reward"]["reputation"] = 6
        commission_file.write_text(json.dumps(commissions, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        delivered = await send("deliver", "交付委托 止血草供应")
        assert delivered.code == "COMMISSION_DELIVERED"
        assert delivered.data["reward_stones"] == 18
        after = max(before, 4)
        assert delivered.data["local_reputation"] == after - before
        assert delivered.data["service_reputation"] == 0
        assert f"地方名望**：+{after - before}" in delivered.message
        assert "服务信誉**：+0" in delivered.message
        conflict = await send("deliver", "交付委托 工具修缮")
        assert conflict.code == "OPERATION_CONFLICT"
        assert "请求编号" not in conflict.message
        await runtime.close()

        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay = await send("deliver", "交付委托 止血草供应")
        assert replay.data == {**delivered.data, "idempotent_replay": True}
        clock.value += timedelta(days=1)
        accept_replay = await send("accept", "接取委托 止血草供应")
        assert accept_replay.data == {**accepted.data, "idempotent_replay": True}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET inventory_json=? WHERE id=?",
                (json.dumps({"item.herb.blood_grass": 3}), player_id),
            )
        assert (await send("next-accept", "接取委托 止血草供应")).ok
        results = await asyncio.gather(
            send("next-deliver", "交付委托 止血草供应"),
            send("other-deliver", "交付委托 止血草供应"),
        )
        assert {result.code for result in results} == {"COMMISSION_DELIVERED", "COMMISSION_ALREADY_DELIVERED"}
        new_result = next(result for result in results if result.ok)
        assert new_result.data["reward_stones"] == 52
        assert new_result.data["local_reputation"] == 8 - after
        with sqlite3.connect(runtime.settings.database_path) as connection:
            stones, local_json, service, cultivation, total = connection.execute(
                "SELECT p.spirit_stones, r.local_json, r.service_reputation, p.cultivation, p.total_cultivation "
                "FROM players p JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
                (player_id,),
            ).fetchone()
        assert stones == 100 + 18 + 52
        assert json.loads(local_json)["local.xuantian.new_town"] == 8
        assert service == 100
        assert (cultivation, total) == (0, 0)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
@pytest.mark.parametrize("change", ["locked_location", "missing_cap", "locked_commission", "different_location"])
def test_frozen_commission_can_finish_and_replay_after_content_changes(
    tmp_path: Path, adapter: str, change: str,
) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        clock = MutableClock()
        location_file = data_dir / "地图" / "地点.json"
        locations = json.loads(location_file.read_text(encoding="utf-8"))
        town = next(row for row in locations["records"] if row["key"] == "xuantian.new_town")
        town["local_reputation_maximum"] = 4
        location_file.write_text(json.dumps(locations, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        base = CommandContext(adapter=adapter, user_id="frozen-commission")

        async def send(operation: str, text: str):
            return await runtime.adapters.dispatch(adapter, replace(base, operation_id=operation), text)

        assert (await send("create", "开始修仙")).ok
        assert (await send("seek", "寻仙问道")).ok
        assert (await send("list", "城镇委托")).ok
        accepted = None
        if change != "different_location":
            accepted = await send("accept", "接取委托 止血草供应")
            assert accepted.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, base.user_id),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, ?, ?)",
                (player_id, json.dumps({"local.xuantian.new_town": 3}), clock.value.isoformat()),
            )
        await runtime.close()

        if change in {"locked_location", "missing_cap"}:
            if change == "locked_location":
                town["status"] = "locked"
            else:
                del town["local_reputation_maximum"]
            location_file.write_text(json.dumps(locations, ensure_ascii=False), encoding="utf-8")
        else:
            commission_file = data_dir / "生活" / "生活.json"
            commissions = json.loads(commission_file.read_text(encoding="utf-8"))
            herb = next(row for row in commissions["records"] if row["key"] == "town_commission.herb_supply")
            if change == "locked_commission":
                herb["status"] = "locked"
            else:
                herb["reward"]["reputation_key"] = "local.xuantian.cloud_city"
                herb["reward"]["amount"] = 52
                herb["reward"]["reputation"] = 6
            commission_file.write_text(json.dumps(commissions, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        if change == "different_location":
            accepted = await send("accept", "接取委托 止血草供应")
            assert accepted.ok
        assert accepted is not None
        replay = await send("accept", "接取委托 止血草供应")
        assert replay.data == {**accepted.data, "idempotent_replay": True}
        if change != "different_location":
            refused = await send("new-accept", "接取委托 止血草供应")
            assert refused.code == "LIVELIHOOD_CONTENT_CLOSED"
        delivered = await send("deliver", "交付委托 止血草供应")
        assert delivered.ok
        assert delivered.data["reward_stones"] == 18
        assert delivered.data["local_reputation"] == 1
        assert delivered.data["service_reputation"] == 1
        await runtime.close()

        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay = await send("deliver", "交付委托 止血草供应")
        assert replay.data == {**delivered.data, "idempotent_replay": True}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            stones, inventory, local_json, service = connection.execute(
                "SELECT p.spirit_stones, p.inventory_json, r.local_json, r.service_reputation "
                "FROM players p JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
                (player_id,),
            ).fetchone()
            delivered_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_name='livelihood.deliver_commission' AND player_id=?",
                (player_id,),
            ).fetchone()[0]
            snapshot = json.loads(connection.execute(
                "SELECT snapshot_json FROM town_commission_claims WHERE claim_id=?",
                (accepted.data["claim_id"],),
            ).fetchone()[0])
        assert stones == 118
        assert "item.herb.blood_grass" not in json.loads(inventory)
        assert json.loads(local_json) == {"local.xuantian.new_town": 4}
        assert service == 1
        assert delivered_count == 1
        assert snapshot["local_reputation_key"] == "local.xuantian.new_town"
        assert snapshot["local_reputation_maximum"] == 4
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["missing_key", "unknown_location", "locked_location", "missing_cap", "boolean_cap"])
def test_commission_reputation_content_rejects_invalid_reference(tmp_path: Path, invalid: str) -> None:
    data_dir = _content(tmp_path)
    path = data_dir / "生活" / "生活.json"
    commissions = json.loads(path.read_text(encoding="utf-8"))
    herb = next(row for row in commissions["records"] if row["key"] == "town_commission.herb_supply")
    if invalid == "missing_key":
        del herb["reward"]["reputation_key"]
    elif invalid == "unknown_location":
        herb["reward"]["reputation_key"] = "local.missing"
    else:
        location_file = data_dir / "地图" / "地点.json"
        locations = json.loads(location_file.read_text(encoding="utf-8"))
        town = next(row for row in locations["records"] if row["key"] == "xuantian.new_town")
        if invalid == "locked_location":
            town["status"] = "locked"
        elif invalid == "missing_cap":
            del town["local_reputation_maximum"]
        else:
            town["local_reputation_maximum"] = True
        location_file.write_text(json.dumps(locations, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(commissions, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="commission town_commission.herb_supply"):
        town_commission_definitions(ContentBundle.load(data_dir))


@pytest.mark.parametrize("local_json", ["{", "[]", '{"local.xuantian.new_town": -1}', '{"local.xuantian.new_town": true}'])
def test_commission_invalid_stored_reputation_rolls_back_assets(tmp_path: Path, local_json: str) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        base = CommandContext(adapter="web", user_id="invalid-commission-reputation")
        assert (await runtime.dispatch(base, "开始修仙")).ok
        assert (await runtime.dispatch(base, "寻仙问道")).ok
        accepted = await runtime.dispatch(replace(base, operation_id="accept"), "接取委托 止血草供应")
        assert accepted.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id, stones, inventory = connection.execute(
                "SELECT id, spirit_stones, inventory_json FROM players WHERE platform_user_id=?",
                (base.user_id,),
            ).fetchone()
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, ?, ?)",
                (player_id, local_json, clock.value.isoformat()),
            )
        with pytest.raises(ValueError):
            await runtime.repository.deliver_commission(
                platform=base.adapter, platform_user_id=base.user_id,
                commission_key="town_commission.herb_supply", operation_id="bad-deliver",
            )
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,),
            ).fetchone()
            claim = connection.execute(
                "SELECT status FROM town_commission_claims WHERE claim_id=?", (accepted.data["claim_id"],),
            ).fetchone()[0]
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='bad-deliver'",
            ).fetchone()[0]
            stored_reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,),
            ).fetchone()[0]
        assert after == (stones, inventory)
        assert claim == "accepted"
        assert operation_count == 0
        assert stored_reputation == local_json
        await runtime.close()

    asyncio.run(run())
