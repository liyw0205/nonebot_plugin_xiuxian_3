from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.world.cloud_rules import cloud_route_definition, resolve_cloud_route
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_definition, resolve_void_route
from nonebot_plugin_xiuxian_3.xiuxian.world_content import validate_world_content
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


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(DATA, data_dir)
    return data_dir


def _edit_record(path: Path, key: str, **changes: object) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == key)
    record.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _prepare_player(
    runtime,
    user: str,
    *,
    realm: str,
    location: str,
    stamina: int,
    spirit_stones: int,
    inventory: dict[str, int] | None = None,
    faction_reputation: dict[str, int] | None = None,
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1, location_key=?, "
            "stamina=?, stamina_max=?, spirit_stones=?, inventory_json=?, faction_reputation_json=? "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (
                realm,
                location,
                stamina,
                stamina,
                spirit_stones,
                json.dumps(inventory or {}, ensure_ascii=False),
                json.dumps(faction_reputation or {}, ensure_ascii=False),
                user,
            ),
        )


def _replace_runtime_content(runtime, data_dir: Path) -> None:
    content = ContentBundle.load(data_dir)
    runtime.content = content
    runtime.repository.content = content
    runtime.application.content = content


def _expire_cloud_boat(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT ends_at FROM cloud_boat_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    ends_at = datetime.fromisoformat(row[0])
    runtime.repository._clock = lambda: ends_at + timedelta(seconds=1)


def test_world_content_requires_cloud_only_destinations_to_use_special_routes() -> None:
    summary = validate_world_content(ContentBundle.load(DATA))
    regions = ContentBundle.load(DATA).list("world_region")
    ordinary_targets = {
        edge["to"]
        for region in regions
        for edge in region["connections"]
    }

    assert summary["connections"] == 61
    assert "cave.mist_grotto_2" not in ordinary_targets
    demon_gate_sources = {
        edge["from"]
        for region in regions
        for edge in region["connections"]
        if edge["to"] == "demon.abyss_gate"
    }
    assert demon_gate_sources == {"demon.fallen_ruins", "demon.abyss_market"}
    assert resolve_cloud_route("云舟魔界引导") == "route.cloud_to_abyss_intro"
    assert cloud_route_definition("route.cloud_to_abyss_intro").destination == "demon.abyss_gate"
    assert resolve_void_route("档案遗迹") == "void.archive_ruins"
    assert void_route_definition("void.archive_ruins").random_pool == "void.route.void.archive_ruins"


@pytest.mark.parametrize(
    ("filename", "key", "changes", "message"),
    [
        ("地图/云舟航线.json", "route.cloud_to_abyss_intro", {"destination": "location.missing"}, "unknown destination"),
        ("地图/云舟航线.json", "route.cloud_to_mist2", {"pass_key": "item.missing"}, "unknown item"),
        ("地图/虚空航线.json", "void.first_route", {"anchor_cost": True}, "anchor_cost"),
    ],
)
def test_transport_content_rejects_invalid_references_and_numbers(
    tmp_path: Path, filename: str, key: str, changes: dict[str, object], message: str
) -> None:
    data_dir = _copy_data(tmp_path)
    _edit_record(data_dir / filename, key, **changes)

    with pytest.raises(ContentError, match=message):
        ContentBundle.load(data_dir)


def test_transport_argument_hints_follow_open_route_content(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _edit_record(
            data_dir / "地图/云舟航线.json",
            "route.cloud_to_abyss_intro",
            command_name="魔界新航线",
        )
        _edit_record(
            data_dir / "地图/虚空航线.json",
            "void.first_route",
            aliases=["初航新名"],
        )
        runtime = create_runtime(data_dir=data_dir)

        cloud_hint = await runtime.adapters.dispatch(
            "onebot.v11", _context("route-hints", "cloud-hint"), "登上云舟"
        )
        assert cloud_hint.code == "INVALID_CLOUD_ROUTE"
        assert "魔界新航线" in cloud_hint.message

        void_hint = await runtime.adapters.dispatch(
            "onebot.v11", _context("route-hints", "void-hint"), "进入虚空航道"
        )
        assert void_hint.code == "INVALID_VOID_ROUTE"
        assert "初航新名" in void_hint.message
        await runtime.close()

    asyncio.run(run())


def test_cloud_route_preview_reports_required_quest_before_start(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _edit_record(
            data_dir / "地图/云舟航线.json",
            "route.cloud_to_abyss_intro",
            required_quest="quest.demon_intro",
        )
        runtime = create_runtime(data_dir=data_dir)
        user = "cloud-route-required-quest"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        _prepare_player(
            runtime,
            user,
            realm="foundation",
            location="xuantian.cloud_city",
            stamina=30,
            spirit_stones=1000,
        )

        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview"), "移动预览 魔界深渊门"
        )
        assert preview.data["travel_mode"] == "cloud_boat"
        assert preview.data["dedicated_route_ready"] is False
        assert "任务权限" in preview.data["missing"]

        started = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "start", "route-requires-quest"), "登上云舟 魔界引导"
        )
        assert started.code == "CLOUD_ROUTE_LOCKED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='route-requires-quest'"
            ).fetchone()[0] == 0
        await runtime.close()

    asyncio.run(run())


def test_ordinary_cross_domain_trip_uses_directional_routes_and_reports_gates(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        user = "ordinary-cross-domain"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        _prepare_player(
            runtime,
            user,
            realm="nascent_soul",
            location="xuantian.floating_boat",
            stamina=30,
            spirit_stones=1000,
        )

        ordinary_preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-cloud-city"), "移动预览 云城"
        )
        assert ordinary_preview.data["travel_mode"] == "ordinary"
        assert ordinary_preview.data["route_available"] is True
        assert ordinary_preview.data["dedicated_route_key"] is None
        assert ordinary_preview.data["duration_seconds"] == 180
        assert ordinary_preview.data["stamina_cost"] == 8
        assert ordinary_preview.data["currency_cost"] == 0
        assert "云舟专用航线" not in ordinary_preview.message

        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-no-reputation"), "移动预览 万兽山"
        )
        assert preview.data["route_available"] is True
        assert preview.data["ready"] is False
        assert "妖界声望" in "、".join(preview.data["missing"])
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT stamina, spirit_stones, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
        denied = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "denied", "denied-cross-domain"), "前往 万兽山"
        )
        assert denied.code == "FACTION_REPUTATION_INSUFFICIENT"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT stamina, spirit_stones, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
            assert after == before
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='denied-cross-domain'"
            ).fetchone()[0] == 0
            connection.execute(
                "UPDATE players SET faction_reputation_json=? "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (json.dumps({"beast": 200}), user),
            )

        outbound_preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-outbound"), "移动预览 万兽山"
        )
        assert outbound_preview.data["ready"] is True
        assert (
            outbound_preview.data["duration_seconds"],
            outbound_preview.data["stamina_cost"],
            outbound_preview.data["currency_cost"],
        ) == (300, 12, 0)
        outbound = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "outbound", "outbound"), "前往 万兽山"
        )
        assert outbound.code == "TRAVEL_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            session = connection.execute(
                "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                (outbound.data["session_id"],),
            ).fetchone()
            snapshot = json.loads(session[0])
            assert snapshot["required_faction"] == "beast"
            assert snapshot["required_faction_reputation"] == 200
            assert snapshot["faction_reputation"] == 200
            set_travel_end_at(
                connection,
                outbound.data["session_id"],
                (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(),
            )
        arrived = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "arrive-outbound", "arrive-outbound"), "结算移动"
        )
        assert arrived.code == "TRAVEL_COMPLETED"

        return_preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-return"), "移动预览 云舟渡口"
        )
        assert return_preview.data["ready"] is True
        assert (
            return_preview.data["duration_seconds"],
            return_preview.data["stamina_cost"],
            return_preview.data["currency_cost"],
        ) == (60, 0, 500)
        returned = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "return", "return"), "前往 云舟渡口"
        )
        assert returned.code == "TRAVEL_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            set_travel_end_at(
                connection,
                returned.data["session_id"],
                (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(),
            )
        return_settled = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "arrive-return", "arrive-return"), "结算移动"
        )
        assert return_settled.code == "TRAVEL_COMPLETED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            final = connection.execute(
                "SELECT stamina, spirit_stones, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
        assert final == (18, 500, "xuantian.floating_boat")
        await runtime.close()

    asyncio.run(run())


def test_cloud_route_data_drives_preview_and_preserves_started_snapshot(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        routes_path = data_dir / "地图/云舟航线.json"
        _edit_record(
            routes_path,
            "route.cloud_to_abyss_intro",
            duration_seconds=420,
            stamina=11,
            spirit_stone=650,
        )
        runtime = create_runtime(data_dir=data_dir)
        user = "cloud-route-content"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        _prepare_player(
            runtime,
            user,
            realm="foundation",
            location="xuantian.cloud_city",
            stamina=30,
            spirit_stones=1000,
        )

        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview"), "移动预览 魔界深渊门"
        )
        assert preview.data["route_available"] is False
        assert preview.data["duration_seconds"] is None
        assert preview.data["travel_mode"] == "cloud_boat"
        assert preview.data["dedicated_route_key"] == "route.cloud_to_abyss_intro"
        assert preview.data["dedicated_route_ready"] is True
        assert preview.data["dedicated_route_duration_seconds"] == 420
        assert preview.data["dedicated_route_stamina_cost"] == 11
        assert preview.data["dedicated_route_currency_cost"] == 650
        assert "不能通过普通移动" in preview.message
        assert "7 分钟（云舟）" in preview.message
        assert "650（云舟）" in preview.message
        assert "登上云舟 魔界引导" in preview.message

        started = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "board", "cloud-board"), "登上云舟 魔界引导"
        )
        assert started.code == "CLOUD_BOAT_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            session = connection.execute(
                "SELECT snapshot_json, starts_at, ends_at FROM cloud_boat_sessions WHERE session_id=?",
                (started.data["session_id"],),
            ).fetchone()
            frozen = json.loads(session[0])
            assert (frozen["stamina_cost"], frozen["currency_cost"]) == (11, 650)
            assert frozen["destination"] == "demon.abyss_gate"
            before_replay = connection.execute(
                "SELECT stamina, spirit_stones, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
            original_end = datetime.fromisoformat(session[2])
            original_start = datetime.fromisoformat(session[1])
        assert (original_end - original_start).total_seconds() == 420

        _edit_record(
            routes_path,
            "route.cloud_to_abyss_intro",
            name="已关闭的云舟航线",
            status="locked",
            duration_seconds=999,
            stamina=1,
            spirit_stone=1,
        )
        _replace_runtime_content(runtime, data_dir)
        replay = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "board-replay", "cloud-board"), "登上云舟 魔界引导"
        )
        assert replay.code == "CLOUD_BOAT_STARTED"
        assert replay.data["idempotent_replay"] is True
        assert replay.data["ends_at"] == started.data["ends_at"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after_replay = connection.execute(
                "SELECT stamina, spirit_stones, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
            assert after_replay == before_replay

        _expire_cloud_boat(runtime, started.data["session_id"])
        settled = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle", "cloud-settle"), "结算云舟"
        )
        assert settled.code == "CLOUD_BOAT_ARRIVED"
        replayed_settlement = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle-replay", "cloud-settle"), "结算云舟"
        )
        assert replayed_settlement.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT location_key FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()[0] == "demon.abyss_gate"
            persisted = json.loads(connection.execute(
                "SELECT snapshot_json FROM cloud_boat_sessions WHERE session_id=?",
                (started.data["session_id"],),
            ).fetchone()[0])
            assert persisted == frozen
        assert original_end == datetime.fromisoformat(started.data["ends_at"])
        await runtime.close()

    asyncio.run(run())


def test_void_route_data_drives_new_trips_but_not_replays_or_settlement(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        routes_path = data_dir / "地图/虚空航线.json"
        _edit_record(
            routes_path,
            "void.first_route",
            duration_seconds=900,
            stamina=18,
            anchor_cost=7,
        )
        runtime = create_runtime(data_dir=data_dir)
        user = "void-route-content"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        _prepare_player(
            runtime,
            user,
            realm="void_refining",
            location="void.portal",
            stamina=50,
            spirit_stones=1000,
            inventory={"item.void_anchor": 20},
        )

        started = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "enter", "void-enter"), "进入虚空航道 第一航道"
        )
        assert started.code == "VOID_ROUTE_STARTED"
        assert started.data["anchor_cost"] == 7
        assert started.data["stamina_cost"] == 18
        with sqlite3.connect(runtime.settings.database_path) as connection:
            session = connection.execute(
                "SELECT snapshot_json, ends_at FROM void_route_sessions WHERE session_id=?",
                (started.data["session_id"],),
            ).fetchone()
            frozen = json.loads(session[0])
            assert frozen["anchor_cost"] == 7
            assert frozen["stamina_cost"] == 18
            assert frozen["random_pool"] == "void.route.void.first_route"
            original_end = datetime.fromisoformat(session[1])
            before_replay = connection.execute(
                "SELECT stamina, inventory_json, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()

        _edit_record(
            routes_path,
            "void.first_route",
            name="已关闭的虚空航线",
            status="locked",
            duration_seconds=1200,
            stamina=1,
            anchor_cost=1,
            random_pool="void.route.changed",
        )
        _replace_runtime_content(runtime, data_dir)
        replay = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "enter-replay", "void-enter"), "进入虚空航道 第一航道"
        )
        assert replay.code == "VOID_ROUTE_STARTED"
        assert replay.data["idempotent_replay"] is True
        assert replay.data["ends_at"] == started.data["ends_at"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina, inventory_json, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone() == before_replay

        runtime.repository._clock = lambda: original_end + timedelta(seconds=1)
        settled = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle", "void-settle"), "结算虚空航道"
        )
        assert settled.code == "VOID_ROUTE_SETTLED"
        replayed_settlement = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "settle-replay", "void-settle"), "结算虚空航道"
        )
        assert replayed_settlement.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT location_key FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()[0] == "void.first_route"
            persisted = json.loads(connection.execute(
                "SELECT snapshot_json FROM void_route_sessions WHERE session_id=?",
                (started.data["session_id"],),
            ).fetchone()[0])
            assert persisted == frozen
        await runtime.close()

    asyncio.run(run())
