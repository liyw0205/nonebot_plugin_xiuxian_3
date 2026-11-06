from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.dao_hall_rules import dao_hall_project_list

ROOT = Path(__file__).parents[1]

MAIN_HALL = "project.dao_hall.main_hall"
LECTURE = "project.dao_hall.lecture_hall"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str, operation: str = ""):
    return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), text)


async def _create_player(
    runtime,
    user: str,
    *,
    merit: int = 3000,
    stones: int = 30000,
    realm_key: str = "tribulation",
    realm_layer: int = 1,
    remain: bool = True,
) -> int:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    values = {
        "stage": "cultivator",
        "world_merit": merit,
        "spirit_stones": stones,
        "realm_key": realm_key,
        "realm_layer": realm_layer,
    }
    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform='onebot.v11' AND platform_user_id=?",
            (*values.values(), user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
        ).fetchone()[0]
        if remain:
            connection.execute(
                "INSERT INTO endgame_endings(player_id, ending_key, status, snapshot_json, "
                "operation_id, created_at) VALUES (?, 'remain_in_world', 'remained_in_world', "
                "'{}', ?, ?)",
                (player_id, f"ending:{user}", "2026-11-03T05:00:00+00:00"),
            )
    return int(player_id)


def _player(runtime, user: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT world_merit, spirit_stones FROM players "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()


def _hall_row(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT hall_id, status, treasury_spirit_stones, contributed_world_merit, "
            "rebuild_ends_at FROM dao_halls"
        ).fetchone()


def _member_rows(runtime) -> list[tuple[str, str]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT p.platform_user_id, m.role FROM dao_hall_members m "
            "JOIN players p ON p.id = m.player_id ORDER BY p.platform_user_id"
        ).fetchall()


def _built(runtime) -> list[str]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT project_key FROM dao_hall_projects ORDER BY project_key"
            ).fetchall()
        ]


def test_founding_requires_the_ending_and_pays_from_the_player() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "mortal", remain=False)
                blocked = await _send(runtime, "mortal", "建立据点", "f-1")
                assert not blocked.ok and blocked.code == "DAO_HALL_REQUIREMENT"
                assert _hall_row(runtime) is None
                assert _player(runtime, "mortal") == (3000, 30000)

                await _create_player(runtime, "poor", merit=1999, stones=4999)
                poor = await _send(runtime, "poor", "建立据点", "f-2")
                assert not poor.ok and poor.code == "DAO_HALL_REQUIREMENT"
                assert _hall_row(runtime) is None
                assert _player(runtime, "poor") == (1999, 4999)

                await _create_player(runtime, "founder")
                status = await _send(runtime, "founder", "据点")
                assert status.ok and status.data["is_member"] is False
                assert status.data["qualified"] is True

                founded = await _send(runtime, "founder", "建立据点", "f-3")
                assert founded.ok and founded.code == "DAO_HALL_FOUND"
                assert founded.data["world_merit_spent"] == 2000
                assert founded.data["spirit_stones_spent"] == 5000
                assert founded.data["treasury_spirit_stones"] == 5000
                assert _player(runtime, "founder") == (1000, 25000)
                row = _hall_row(runtime)
                assert row[1] == "active" and row[2] == 5000
                assert _member_rows(runtime) == [("founder", "founder")]
            finally:
                await runtime.close()

    asyncio.run(run())


def test_core_seats_guests_and_the_founder_lock() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "founder")
                assert (await _send(runtime, "founder", "建立据点", "f-1")).ok

                # A 渡劫 cultivator takes a core seat.
                await _create_player(runtime, "core", realm_key="tribulation", remain=False)
                joined = await _send(runtime, "core", "加入据点", "j-1")
                assert joined.ok and joined.code == "DAO_HALL_JOIN"
                assert joined.data["core_members"] == 2

                # A low-realm visitor never occupies a core seat.
                await _create_player(
                    runtime, "guest", realm_key="qi_sensing", realm_layer=3, remain=False
                )
                guest = await _send(runtime, "guest", "加入据点", "j-2")
                assert guest.ok and guest.data["core_members"] == 2
                assert ("guest", "guest") in _member_rows(runtime)

                duplicate = await _send(runtime, "guest", "加入据点", "j-3")
                assert not duplicate.ok and duplicate.code == "DAO_HALL_ALREADY_JOINED"

                founder_leave = await _send(runtime, "founder", "退出据点", "l-1")
                assert not founder_leave.ok and founder_leave.code == "DAO_HALL_FOUNDER_LOCKED"

                left = await _send(runtime, "guest", "退出据点", "l-2")
                assert left.ok and left.code == "DAO_HALL_LEAVE"
                assert ("guest", "guest") not in _member_rows(runtime)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_construction_needs_merit_and_unlocks_its_effects() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "builder", merit=9000)
                assert (await _send(runtime, "builder", "建立据点", "f-1")).ok

                locked = await _send(runtime, "builder", "建设据点 讲道台", "b-1")
                assert not locked.ok and locked.code == "DAO_HALL_PROJECT_LOCKED"
                assert _built(runtime) == []

                built = await _send(runtime, "builder", "建设据点 太清殿", "b-2")
                assert built.ok and built.code == "DAO_HALL_BUILD"
                assert built.data["core_capacity"] == 30
                assert built.data["build_ends_at"] is not None
                assert built.data["world_merit_spent"] == 800
                assert _player(runtime, "builder")[0] == 9000 - 2000 - 800
                assert _built(runtime) == []

                clock.advance(hours=24)
                completed = await _send(runtime, "builder", "据点")
                assert completed.ok
                assert completed.data["core_capacity"] == 35
                assert completed.data["built_project_keys"] == [MAIN_HALL]
                assert completed.data["maintenance_due"] == 5000

                again = await _send(runtime, "builder", "建设据点 正殿", "b-3")
                assert not again.ok and again.code == "DAO_HALL_PROJECT_BUILT"

                lecture = await _send(runtime, "builder", "建设据点 讲道台", "b-4")
                assert lecture.ok and lecture.data["world_merit_spent"] == 600
                assert lecture.data["build_ends_at"] is not None

                unknown = await _send(runtime, "builder", "建设据点 不存在", "b-5")
                assert not unknown.ok and unknown.code == "DAO_HALL_PROJECT_NOT_FOUND"

                clock.advance(hours=18)
                status = await _send(runtime, "builder", "据点")
                assert set(status.data["built_project_keys"]) == {MAIN_HALL, LECTURE}
                assert status.data["maintenance_due"] == 4500
                assert _hall_row(runtime)[3] == 1400
            finally:
                await runtime.close()

    asyncio.run(run())


def test_maintenance_bills_the_treasury_then_the_member() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "keeper")
                assert (await _send(runtime, "keeper", "建立据点", "f-1")).ok

                early = await _send(runtime, "keeper", "维护据点", "m-1")
                assert not early.ok and early.code == "DAO_HALL_MAINTENANCE_NOT_DUE"

                clock.advance(days=7, hours=1)
                first = await _send(runtime, "keeper", "维护据点", "m-2")
                assert first.ok and first.data["spirit_stones_spent"] == 5000
                # Week one is paid from the founding treasury.
                assert first.data["treasury_spirit_stones"] == 0
                assert _player(runtime, "keeper") == (1000, 25000)

                clock.advance(days=7)
                second = await _send(runtime, "keeper", "维护据点", "m-3")
                assert second.ok and second.data["spirit_stones_spent"] == 5000
                # The treasury is empty, so the member covers it.
                assert _player(runtime, "keeper") == (1000, 20000)
                assert second.data["treasury_spirit_stones"] == 0
            finally:
                await runtime.close()

    asyncio.run(run())


def test_rebuilding_keeps_members_and_blocks_growth_until_it_elapses() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "warden")
                assert (await _send(runtime, "warden", "建立据点", "f-1")).ok
                await _create_player(runtime, "late", realm_key="tribulation", remain=False)

                damaged = await runtime.repository.damage_dao_hall(
                    platform="onebot.v11", platform_user_id="warden", operation_id="d-1"
                )
                assert damaged.status == "rebuilding"
                assert damaged.rebuild_ends_at == "2026-11-06T05:00:00+00:00"

                joined = await _send(runtime, "late", "加入据点", "j-1")
                assert not joined.ok and joined.code == "DAO_HALL_REBUILDING"

                building = await _send(runtime, "warden", "建设据点 太清殿", "b-1")
                assert not building.ok and building.code == "DAO_HALL_REBUILDING"
                assert _built(runtime) == []

                clock.advance(days=7, hours=1)
                free = await _send(runtime, "warden", "维护据点", "m-1")
                assert free.ok and free.data["spirit_stones_spent"] == 0
                assert _player(runtime, "warden") == (1000, 25000)

                clock.advance(days=3)
                recovered = await _send(runtime, "warden", "据点")
                assert recovered.ok and recovered.data["status"] == "active"
                assert recovered.data["core_members"] == 1
                assert _member_rows(runtime) == [("warden", "founder")]

                after = await _send(runtime, "late", "加入据点", "j-2")
                assert after.ok and after.code == "DAO_HALL_JOIN"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_replay_is_idempotent_and_state_survives_a_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "replayer", merit=9000)
                first = await _send(runtime, "replayer", "建立据点", "f-1")
                assert first.ok
                balance = _player(runtime, "replayer")

                replay = await _send(runtime, "replayer", "建立据点", "f-1")
                assert replay.ok and replay.data["already_completed"] is True
                assert replay.data["hall_id"] == first.data["hall_id"]
                assert _player(runtime, "replayer") == balance
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM dao_halls").fetchone()[0] == 1

                built = await _send(runtime, "replayer", "建设据点 太清殿", "b-1")
                assert built.ok
                built_replay = await _send(runtime, "replayer", "建设据点 太清殿", "b-1")
                assert built_replay.ok and built_replay.data["already_completed"] is True
                assert _built(runtime) == []
                assert _player(runtime, "replayer") == (9000 - 2000 - 800, 25000)

                clock.advance(hours=24)
                status = await _send(runtime, "replayer", "据点")
                assert status.ok
                assert status.data["built_project_keys"] == [MAIN_HALL]
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                status = await _send(reopened, "replayer", "据点")
                assert status.ok
                assert status.data["role"] == "founder"
                assert set(status.data["built_project_keys"]) == {MAIN_HALL}
                assert status.data["core_capacity"] == 35
                assert status.data["treasury_spirit_stones"] == 5000
            finally:
                await reopened.close()

    asyncio.run(run())


def test_hall_does_not_touch_ascension_or_season_state() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "watch")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = connection.execute(
                        "SELECT ascension_merit, tribulation_debt, dao_fruit_progress "
                        "FROM players WHERE platform_user_id='watch'"
                    ).fetchone()
                assert (await _send(runtime, "watch", "建立据点", "f-1")).ok
                await _send(runtime, "watch", "建设据点 太清殿", "b-1")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = connection.execute(
                        "SELECT ascension_merit, tribulation_debt, dao_fruit_progress "
                        "FROM players WHERE platform_user_id='watch'"
                    ).fetchone()
                    season_rows = connection.execute(
                        "SELECT COUNT(*) FROM final_heaven_rankings"
                    ).fetchone()[0]
                assert after == before
                assert season_rows == 0
            finally:
                await runtime.close()

    asyncio.run(run())


def test_rendering_keeps_blue_links_one_action_and_onebot_fallback() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                before = await _send(runtime, "render", "据点")
                assert before.ok and before.actions == ()
                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", before.message)
                ]
                assert "建立据点" in links
                text = markdown_to_text(before.message)
                assert "command:" not in text
                assert "hall.dao_settlement" not in before.message

                assert (await _send(runtime, "render", "建立据点", "f-1")).ok
                after = await _send(runtime, "render", "据点")
                assert [action.label for action in after.actions] == ["维护据点"]

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    after.message,
                    capabilities=("text",),
                    actions=after.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：维护据点")
                assert "command:" not in str(bot.sent[0])

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    after.message,
                    capabilities=("markdown", "keyboard"),
                    actions=after.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert "keyboard" in str(qq_bot.sent[0])
                assert "hall.dao_settlement" not in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 社交")
                assert help_page.code == "HELP_CATEGORY"
                assert "留界据点" in help_page.message
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())

def test_construction_hours_content_contract() -> None:
    projects = {
        project.key: project
        for project in dao_hall_project_list(ContentBundle.load(ROOT / "data"))
    }
    assert projects[MAIN_HALL].build_hours == 24
    assert projects[LECTURE].build_hours == 18
    assert projects["project.dao_hall.ward_array"].build_hours == 36

    with TemporaryDirectory() as data_dir:
        shutil.copytree(ROOT / "data", data_dir, dirs_exist_ok=True)
        path = Path(data_dir) / "社交" / "道统据点.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document["records"]:
            if record.get("key") == MAIN_HALL:
                del record["build_hours"]
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with pytest.raises(ContentError, match="build_hours"):
            dao_hall_project_list(ContentBundle.load(data_dir))


def test_construction_is_serialized_and_waits_for_completion() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "busy", merit=9000)
                assert (await _send(runtime, "busy", "建立据点", "f-1")).ok
                first = await _send(runtime, "busy", "建设据点 太清殿", "b-1")
                assert first.ok and first.data["build_ends_at"]
                assert _built(runtime) == []

                blocked = await _send(runtime, "busy", "建设据点 讲道台", "b-2")
                assert not blocked.ok and blocked.code == "DAO_HALL_CONSTRUCTION_BUSY"
                assert _player(runtime, "busy")[0] == 9000 - 2000 - 800

                status = await _send(runtime, "busy", "据点")
                assert status.ok
                assert status.data["construction_project_key"] == MAIN_HALL
                assert status.data["built_project_keys"] == []

                clock.advance(hours=24)
                status = await _send(runtime, "busy", "据点")
                assert status.data["built_project_keys"] == [MAIN_HALL]
                assert status.data["construction_project_key"] is None
            finally:
                await runtime.close()

    asyncio.run(run())


def test_settlement_route_shortens_construction_by_1500_bp() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                player_id = await _create_player(runtime, "route", merit=9000)
                assert (await _send(runtime, "route", "建立据点", "f-1")).ok
                now_text = clock.value.isoformat()
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO sects(sect_id, name, name_key, leader_id, status, level, "
                        "max_members, warehouse_capacity, construction, spirit_stones, "
                        "sect_merit, warehouse_json, created_at, updated_at) "
                        "VALUES ('sect-test', '测试宗', 'test-sect', ?, 'active', 6, 80, "
                        "100, 0, 0, 1000, '{}', ?, ?)",
                        (player_id, now_text, now_text),
                    )
                    connection.execute(
                        "INSERT INTO sect_members(sect_id, player_id, role, status, "
                        "contribution, joined_at, last_action_at, created_at, updated_at) "
                        "VALUES ('sect-test', ?, 'leader', 'active', 0, ?, ?, ?, ?)",
                        (player_id, now_text, now_text, now_text, now_text),
                    )
                    connection.execute(
                        "INSERT INTO dao_route_state(sect_id, route_key, cycle_id, "
                        "locked_until, updated_at) VALUES "
                        "('sect-test', 'route.dao_settlement.remain', 'route:test', ?, ?)",
                        ((clock.value + timedelta(days=7)).isoformat(), now_text),
                    )
                started = clock.value
                built = await _send(runtime, "route", "建设据点 太清殿", "b-1")
                assert built.ok
                ends_at = datetime.fromisoformat(built.data["build_ends_at"])
                assert int((ends_at - started).total_seconds()) == 75130

                clock.advance(hours=20, minutes=52, seconds=10)
                status = await _send(runtime, "route", "据点")
                assert status.data["built_project_keys"] == [MAIN_HALL]
            finally:
                await runtime.close()

    asyncio.run(run())
