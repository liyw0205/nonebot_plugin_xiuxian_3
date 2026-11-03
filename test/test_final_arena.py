from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ARENA_LOCATION = "location.final_arena"
TERRACE = "tribulation.sky_terrace"
TIER_1 = "tier.final_arena.1"
TIER_2 = "tier.final_arena.2"
TIER_3 = "tier.final_arena.3"


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


async def _create_player(runtime, user: str, **fields) -> None:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    values = {
        "stage": "cultivator",
        "realm_key": "tribulation",
        "realm_layer": 6,
        "location_key": ARENA_LOCATION,
        "stamina": 500,
        "stamina_max": 500,
        "max_hp": 200000,
        "qualification_json": json.dumps(BALANCED_QUALIFICATION),
        **fields,
    }
    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform='onebot.v11' AND platform_user_id=?",
            (*values.values(), user),
        )
    equip_damage_weapon(runtime, "onebot.v11", user, 70000)


def _player(runtime, user: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT stamina, spirit_stones, inventory_json, location_key, endgame_status, "
            "tribulation_debt, dao_fruit_progress, ascension_merit "
            "FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()


def _count(runtime, table: str, where: str = "1=1") -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        )


def test_arena_travel_gate_and_round_window() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(
                    runtime, "walker", location_key=TERRACE, realm_layer=5
                )
                low = await _send(runtime, "walker", "移动预览 终局天榜")
                assert low.code == "TRAVEL_PREVIEW"
                assert any("境界要求" in item for item in low.data["missing"]), low.data

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_layer=6 WHERE platform_user_id='walker'"
                    )
                ok = await _send(runtime, "walker", "移动预览 终局天榜")
                assert ok.data["missing"] == (), ok.data

                clock.value = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
                closed_preview = await _send(runtime, "walker", "移动预览 终局天榜")
                assert "天榜活动轮次" in closed_preview.data["missing"], closed_preview.data
                closed = await _send(runtime, "walker", "前往 终局天榜", "closed-travel")
                assert closed.code == "EVENT_NOT_ACTIVE", closed
                assert _player(runtime, "walker")[3] == TERRACE
                assert _count(runtime, "travel_sessions") == 0

                clock.value = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
                started = await _send(runtime, "walker", "前往 终局天榜", "arena-travel")
                assert started.code == "TRAVEL_STARTED", started
                clock.advance(minutes=16)
                settled = await _send(runtime, "walker", "结算移动", "arena-travel-settle")
                assert settled.code == "TRAVEL_COMPLETED", settled
                assert _player(runtime, "walker")[3] == ARENA_LOCATION

                away = await _send(runtime, "walker", "终局天榜")
                assert away.data["at_location"] is True
                assert away.data["open"] is True
                assert away.data["qualified"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_arena_ladder_cap_and_display_only_rewards() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "ladder")
                before = _player(runtime, "ladder")
                operations_before = _count(runtime, "operations")

                preview = await _send(runtime, "ladder", "终局天榜")
                assert preview.code == "FINAL_ARENA_PREVIEW"
                assert preview.data["round_id"].startswith("final_arena:")
                assert preview.data["attempt_limit"] == 3
                assert preview.data["attempts_used"] == 0
                assert preview.data["best_tier"] == 0
                assert [tier["label"] for tier in preview.data["tiers"]] == [
                    "天榜初阶",
                    "天榜中阶",
                    "天榜上阶",
                ]
                assert preview.data["tiers"][0]["unlocked"] is True
                assert preview.data["tiers"][1]["unlocked"] is False
                assert "购买" not in preview.message
                assert "command:" in preview.message
                assert "tier.final_arena" not in preview.message
                # Preview is read-only.
                assert _count(runtime, "operations") == operations_before
                assert _count(runtime, "final_arena_challenges") == 0

                locked = await _send(runtime, "ladder", "挑战天榜 天榜上阶", "locked-tier")
                assert locked.code == "FINAL_ARENA_TIER_LOCKED"
                assert _count(runtime, "final_arena_challenges") == 0

                first = await _send(runtime, "ladder", "挑战天榜 初阶", "tier-1")
                assert first.code == "FINAL_ARENA_SETTLED", first
                assert first.data["outcome"] == "won", first.data
                assert first.data["best_tier"] == 1
                assert first.data["attempts_used"] == 1
                assert first.actions and first.actions[0].command == "终局天榜"
                after_one = _player(runtime, "ladder")
                assert after_one[0] == before[0] - 15
                assert after_one[1] == before[1]
                assert after_one[4] == before[4] == "none"
                assert after_one[5] == before[5] == 0
                assert after_one[6] == before[6] == 0
                assert after_one[7] == before[7] == 0
                assert json.loads(after_one[2]) == json.loads(before[2])

                replay = await _send(runtime, "ladder", "挑战天榜 初阶", "tier-1")
                assert replay.code == "FINAL_ARENA_SETTLED"
                assert replay.data["idempotent_replay"] is True
                assert _player(runtime, "ladder")[0] == after_one[0]
                assert _count(runtime, "final_arena_challenges") == 1

                conflict = await _send(runtime, "ladder", "挑战天榜 中阶", "tier-1")
                assert conflict.code == "LEDGER_CONFLICT"
                assert _count(runtime, "final_arena_challenges") == 1

                second = await _send(runtime, "ladder", "挑战天榜 中阶", "tier-2")
                third = await _send(runtime, "ladder", "挑战天榜 上阶", "tier-3")
                assert second.data["best_tier"] == 2
                assert third.data["outcome"] == "won", third.data
                assert third.data["best_tier"] == 3
                assert third.data["title_granted"] == "title.final_arena.summit"
                assert third.data["summit_cleared"] is True

                capped = await _send(runtime, "ladder", "挑战天榜 初阶", "tier-4")
                assert capped.code == "FINAL_ARENA_ATTEMPT_CAP"
                assert "未扣除体力" in capped.message
                assert _count(runtime, "final_arena_challenges") == 3
                assert _player(runtime, "ladder")[0] == before[0] - 45
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    titles = connection.execute(
                        "SELECT title_key FROM honor_titles"
                    ).fetchall()
                    progress = connection.execute(
                        "SELECT best_tier, summit_cleared FROM final_arena_progress"
                    ).fetchone()
                    events = connection.execute(
                        "SELECT COUNT(*) FROM activity_events WHERE event_key='final_arena.challenge'"
                    ).fetchone()
                assert [row[0] for row in titles] == ["title.final_arena.summit"]
                assert progress == (3, 1)
                assert int(events[0]) == 3

                # The title is granted once even after a full replay.
                replay_summit = await _send(runtime, "ladder", "挑战天榜 上阶", "tier-3")
                assert replay_summit.data["idempotent_replay"] is True
                assert _count(runtime, "honor_titles") == 1

                # The next round resets the attempt counter.
                clock.advance(hours=4)
                next_round = await _send(runtime, "ladder", "终局天榜")
                assert next_round.data["attempts_used"] == 0
                assert next_round.data["best_tier"] == 3
                assert next_round.data["summit_cleared"] is True
                assert next_round.data["round_id"] != preview.data["round_id"]
                resumed = await _send(runtime, "ladder", "挑战天榜 初阶", "tier-5")
                assert resumed.ok and resumed.data["attempts_used"] == 1
            finally:
                await runtime.close()

    asyncio.run(run())


def test_arena_refusals_are_zero_write() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "away", location_key=TERRACE)
                away_preview = await _send(runtime, "away", "终局天榜")
                assert away_preview.data["at_location"] is False
                assert "终局天榜" in away_preview.message
                away = await _send(runtime, "away", "挑战天榜 初阶", "away")
                assert away.code == "FINAL_ARENA_LOCATION_REQUIRED"
                assert _count(runtime, "final_arena_challenges") == 0

                await _create_player(runtime, "weak", realm_key="void_refining", realm_layer=10)
                weak = await _send(runtime, "weak", "终局天榜")
                assert weak.data["qualified"] is False
                weak_challenge = await _send(runtime, "weak", "挑战天榜 初阶", "weak")
                assert weak_challenge.code == "FINAL_ARENA_LOCATION_REQUIRED"
                assert _count(runtime, "final_arena_challenges") == 0

                await _create_player(runtime, "tired", stamina=10)
                tired = await _send(runtime, "tired", "挑战天榜 初阶", "tired")
                assert tired.code == "STAMINA_INSUFFICIENT"
                assert _player(runtime, "tired")[0] == 10
                assert _count(runtime, "final_arena_challenges") == 0

                await _create_player(runtime, "outside", location_key=ARENA_LOCATION)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='tribulation.sky_terrace' "
                        "WHERE platform_user_id='outside'"
                    )
                # Window closed: the challenge refuses even from the right realm.
                clock.value = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
                closed = await _send(runtime, "outside", "挑战天榜 初阶", "closed")
                assert closed.code == "FINAL_ARENA_NOT_OPEN"
                assert "未扣除体力" in closed.message
                assert _count(runtime, "final_arena_challenges") == 0
                assert _player(runtime, "outside")[0] == 500

                for command, code in (
                    ("挑战天榜", "INVALID_FINAL_ARENA_COMMAND"),
                    ("挑战天榜 不存在", "INVALID_FINAL_ARENA_COMMAND"),
                    ("结算天榜", "FINAL_ARENA_CHALLENGE_NOT_FOUND"),
                    ("终局天榜 初阶 中阶", "INVALID_FINAL_ARENA_COMMAND"),
                ):
                    rejected = await _send(runtime, "outside", command, f"reject-{command}")
                    assert rejected.code == code, (command, rejected)

                stranger = await _send(runtime, "no-player", "终局天榜")
                assert stranger.code == "PLAYER_NOT_FOUND"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_arena_survives_restart_and_settlement_replay() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "restart")
                first = await _send(runtime, "restart", "挑战天榜 初阶", "restart-1")
                assert first.ok and first.data["best_tier"] == 1
                stamina = _player(runtime, "restart")[0]
                assert _count(runtime, "final_arena_challenges", "status='open'") == 0
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                preview = await _send(reopened, "restart", "终局天榜")
                assert preview.data["best_tier"] == 1
                assert preview.data["attempts_used"] == 1
                assert _player(reopened, "restart")[0] == stamina
                replay = await _send(reopened, "restart", "挑战天榜 初阶", "restart-1")
                assert replay.code == "FINAL_ARENA_SETTLED"
                assert replay.data["idempotent_replay"] is True
                assert _player(reopened, "restart")[0] == stamina
                second = await _send(reopened, "restart", "挑战天榜 中阶", "restart-2")
                assert second.ok and second.data["best_tier"] == 2
            finally:
                await reopened.close()

    asyncio.run(run())


def test_adapter_rendering_keeps_blue_links_and_onebot_fallback() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                listed = await _send(runtime, "render", "终局天榜")
                single = await _send(runtime, "render", "终局天榜 初阶")
                assert listed.actions == ()
                assert single.actions and single.actions[0].label == "挑战此层级"

                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", listed.message)
                ]
                assert links and all(link.startswith("挑战天榜 ") for link in links)
                text = markdown_to_text(listed.message)
                assert "挑战天榜 天榜初阶" in text
                assert "command:" not in text
                assert "tier.final_arena" not in listed.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    single.message,
                    capabilities=("text",),
                    actions=single.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：挑战天榜 天榜初阶")
                assert "command:" not in str(bot.sent[0])

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    single.message,
                    capabilities=("markdown", "keyboard"),
                    actions=single.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert native.degraded is False
                assert "keyboard" in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 探索")
                assert help_page.code == "HELP_CATEGORY"
                assert "终局天榜" in help_page.message
                assert "挑战天榜 天榜初阶" in markdown_to_text(help_page.message)
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())


def test_unfinished_challenge_blocks_restart_and_settles_by_refund() -> None:
    """A challenge whose battle never started must refund, not report a win."""

    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "orphan")
                # Freeze the entry without running the battle: this is the state
                # a process death between the entry write and the battle start
                # leaves behind.
                await runtime.repository.start_final_arena_challenge.__wrapped__ if False else None
                record = await runtime.repository.preview_final_arena(
                    platform="onebot.v11", platform_user_id="orphan"
                )
                assert record.attempts_used == 0

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO final_arena_challenges("
                        " challenge_id, player_id, round_id, starts_at, ends_at, tier_key, tier_no,"
                        " enemy_key, status, snapshot_json, operation_id, created_at"
                        ") SELECT 'orphan-1', id, ?, ?, ?, 'tier.final_arena.1', 1,"
                        " 'enemy.final_arena_guardian_1', 'open', ?, 'orphan-op-1', ?"
                        " FROM players WHERE platform_user_id='orphan'",
                        (
                            record.round_id,
                            record.starts_at,
                            record.ends_at,
                            json.dumps(
                                {
                                    "tier_key": "tier.final_arena.1",
                                    "tier_no": 1,
                                    "enemy_key": "enemy.final_arena_guardian_1",
                                    "title_key": None,
                                    "round_id": record.round_id,
                                    "season_id": "season.final_heaven:20261028",
                                    "location_key": ARENA_LOCATION,
                                    "stamina_cost": 15,
                                    "attempt_limit": 3,
                                    "attempts_used_before": 0,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            clock.value.isoformat(),
                        ),
                    )
                    connection.execute(
                        "UPDATE operations SET result_json='{}' WHERE 1=0"
                    )
                stamina_before = _player(runtime, "orphan")[0]

                blocked = await _send(runtime, "orphan", "挑战天榜 初阶", "orphan-start")
                assert blocked.code == "BATTLE_BUSY", blocked
                assert _player(runtime, "orphan")[0] == stamina_before

                settled = await _send(runtime, "orphan", "结算天榜", "orphan-settle")
                assert settled.code == "FINAL_ARENA_SETTLED", settled
                assert settled.data["outcome"] == "expired", settled.data
                assert settled.data["status"] == "expired"
                assert _player(runtime, "orphan")[0] == stamina_before + 15
                progress = await _send(runtime, "orphan", "终局天榜")
                assert progress.data["best_tier"] == 0
                assert progress.data["attempts_used"] == 0
            finally:
                await runtime.close()

    asyncio.run(run())
