from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from travel_fixtures import set_travel_end_at


ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"


def _context(user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter="onebot.v11",
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _route_document(data_dir: Path) -> tuple[Path, dict]:
    path = data_dir / "地图/区域.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    region = next(row for row in document["records"] if row["key"] == "region.xuantian.qingshi")
    route = next(
        edge for edge in region["connections"]
        if edge["from"] == "xuantian.new_town" and edge["to"] == "xuantian.outskirts"
    )
    return path, {"document": document, "region": region, "route": route}


def _state(runtime, user: str) -> tuple[tuple, tuple, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()
        session = connection.execute(
            "SELECT status, snapshot_json FROM travel_sessions WHERE player_id=("
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?) "
            "ORDER BY id DESC LIMIT 1",
            (user,),
        ).fetchone()
        operations = connection.execute(
            "SELECT COUNT(*) FROM operations WHERE player_id=("
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?)",
            (user,),
        ).fetchone()[0]
    return player, session, int(operations)


def test_route_contract_gates_costs_and_snapshot_survive_map_change(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(DATA, data_dir)
        path, records = _route_document(data_dir)
        route = records["route"]
        route.update(
            duration_seconds=77,
            stamina=9,
            spirit_stone=3,
            item_key="item.cave_pass_basic",
            item_quantity=2,
            consume_pass_on_arrival=True,
            requirements=[{"type": "item", "item_key": "item.cave_pass_basic", "quantity": 2}],
        )
        path.write_text(
            json.dumps(records["document"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        runtime = create_runtime(data_dir=data_dir)
        user = "route-contract"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=1, "
                "location_key='xuantian.new_town', stamina=30, stamina_max=30, spirit_stones=100, "
                "inventory_json=? WHERE platform='onebot.v11' AND platform_user_id=?",
                (json.dumps({"item.cave_pass_basic": 1}), user),
            )

        wrong_source = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "wrong-source-preview"), "移动预览 cave.mist_grotto"
        )
        assert wrong_source.code == "TRAVEL_PREVIEW"
        assert wrong_source.data["ready"] is False
        assert "来源地点" in wrong_source.data["missing"]
        denied_route = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "wrong-source", "wrong-source-op"), "前往 cave.mist_grotto"
        )
        assert denied_route.code == "TRAVEL_ROUTE_INVALID"
        assert _state(runtime, user)[1] is None
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='wrong-source-op'"
            ).fetchone()[0] == 0

        missing_pass = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "gated-preview"), "移动预览 玄天近郊"
        )
        assert missing_pass.code == "TRAVEL_PREVIEW"
        assert missing_pass.data["ready"] is False
        assert "通行物品" in missing_pass.data["missing"]
        before = _state(runtime, user)
        denied_gate = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "gated-start", "gated-start-op"), "前往 玄天近郊"
        )
        assert denied_gate.code == "LOCATION_REQUIREMENT_MISSING"
        assert _state(runtime, user) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='gated-start-op'"
            ).fetchone()[0] == 0

        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET inventory_json=? WHERE platform='onebot.v11' AND platform_user_id=?",
                (json.dumps({"item.cave_pass_basic": 2}), user),
            )
        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "valid-preview"), "移动预览 玄天近郊"
        )
        assert preview.data["ready"] is True
        assert (preview.data["duration_seconds"], preview.data["stamina_cost"], preview.data["currency_cost"]) == (77, 9, 3)

        started = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "start", "start-op"), "前往 玄天近郊"
        )
        assert started.code == "TRAVEL_STARTED"
        player, session, operation_count = _state(runtime, user)
        assert player[:2] == (21, 97)
        assert json.loads(player[2]) == {"item.cave_pass_basic": 2}
        assert session is not None and session[0] == "running"
        snapshot = json.loads(session[1])
        assert (snapshot["stamina_cost"], snapshot["currency_cost"]) == (9, 3)
        assert (snapshot["pass_key"], snapshot["pass_quantity"]) == ("item.cave_pass_basic", 2)
        assert snapshot["consume_pass_on_arrival"] is True
        assert operation_count == 2

        await runtime.close()
        records["region"]["status"] = "locked"
        path.write_text(
            json.dumps(records["document"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        runtime = create_runtime(data_dir=data_dir)
        replay = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "start-replay", "start-op"), "前往 玄天近郊"
        )
        assert replay.code == "TRAVEL_STARTED"
        assert replay.data["idempotent_replay"] is True
        assert _state(runtime, user) == (player, session, operation_count)

        with sqlite3.connect(runtime.settings.database_path) as connection:
            expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            set_travel_end_at(connection, started.data["session_id"], expired)
        settled = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle", "settle-op"), "结算移动"
        )
        assert settled.code == "TRAVEL_COMPLETED"
        assert "雾隐洞天凭证 ×2已在抵达时消耗。" in settled.message
        player, session, operation_count = _state(runtime, user)
        assert (player[0], player[1], player[3]) == (21, 97, "xuantian.outskirts")
        assert json.loads(player[2]) == {}
        assert session is not None and session[0] == "arrived"
        assert operation_count == 3
        await runtime.close()

    asyncio.run(run())


def test_route_daily_start_limit_is_used_by_preview_and_transaction(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(DATA, data_dir)
        path, records = _route_document(data_dir)
        records["route"]["daily_start_limit"] = 1
        path.write_text(
            json.dumps(records["document"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
        user = "route-daily-limit"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=1, "
                "location_key='xuantian.new_town', stamina=30, stamina_max=30 "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            )

        started = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "start-1", "start-1"), "前往 玄天近郊"
        )
        assert started.code == "TRAVEL_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            set_travel_end_at(connection, started.data["session_id"], "2026-10-15T00:00:00+00:00")
        settled = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle-1", "settle-1"), "结算移动"
        )
        assert settled.code == "TRAVEL_COMPLETED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET location_key='xuantian.new_town', stamina=30 "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            )

        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-2"), "移动预览 玄天近郊"
        )
        assert preview.code == "TRAVEL_PREVIEW"
        assert preview.data["ready"] is False
        assert "今日访问次数" in preview.data["missing"]
        before = _state(runtime, user)
        denied = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "start-2", "start-2"), "前往 玄天近郊"
        )
        assert denied.code == "LOCATION_REQUIREMENT_MISSING"
        assert _state(runtime, user) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='start-2'"
            ).fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run())
