from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.events.season_rules import final_heaven_tie_breaker
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _adapter_contexts():
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="season-qq-message",
            content="终局赛季",
            timestamp="2026-09-23T20:05:00+00:00",
            author=GroupMemberAuthor(
                id="qq-raw", bot=False, member_openid="season-qq-user", username="隐私道号"
            ),
            group_id="qq-raw-group",
            group_openid="season-qq-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_650_700,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2002,
            message_type="group",
            message_id=9003,
            message=Message("终局赛季"),
            original_message=Message("终局赛季"),
            raw_message="终局赛季",
            font=0,
            sender=Sender(user_id=2002, nickname="OneBot隐私道号"),
            group_id=3001,
        )
    ).context
    return qq, onebot


def test_final_heaven_rankings_freeze_anonymously_and_claim_once_across_adapters() -> None:
    async def run() -> None:
        initial = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)
        season_id, starts_at, ends_at = final_heaven_season_window(initial)
        clock = MutableClock(starts_at + timedelta(days=5))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            actors = [
                ("ascender-private-id", qq, "ascender"),
                ("remainer-private-id", onebot, "remainer"),
                ("helper-private-id", qq, "helper"),
            ]
            for user_id, context, prefix in actors:
                actor = replace(context, user_id=user_id, operation_id=f"{prefix}-create")
                assert (
                    await runtime.adapters.dispatch(actor.adapter, actor, "开始修仙")
                ).code == "PLAYER_CREATED"
                assert (
                    await runtime.adapters.dispatch(
                        actor.adapter,
                        replace(actor, operation_id=f"{prefix}-seek"),
                        "寻仙问道",
                    )
                ).code == "SEEKING_STARTED"

            def seed_records() -> None:
                start_text = (starts_at + timedelta(days=1)).isoformat()
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_ids = dict(
                        connection.execute("SELECT platform_user_id, id FROM players").fetchall()
                    )
                    for user_id, ending_key, status, suffix in (
                        ("ascender-private-id", "ascend", "ascended", "a"),
                        ("remainer-private-id", "remain_in_world", "remained_in_world", "d"),
                    ):
                        connection.execute(
                            "INSERT INTO endgame_endings(player_id, ending_key, status, fruit_key, snapshot_json, operation_id, content_version, rule_version, created_at) "
                            "VALUES (?, ?, ?, ?, '{}', ?, 'content-0.6', 'progression-0.6.1', ?)",
                            (player_ids[user_id], ending_key, status, "fruit.dao" if suffix == "d" else None, f"ending-{suffix}", start_text),
                        )
                    battle_id = "season-coop-success"
                    connection.execute(
                        "INSERT INTO final_battle_sessions(battle_id, initiator_id, create_operation_id, status, round_no, action_sequence, starts_at, expires_at, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'settled', 3, 8, ?, ?, '{}', '{}', ?, 'content-0.6', 'combat-0.6.1', ?, ?)",
                        (
                            battle_id,
                            player_ids["ascender-private-id"],
                            "season-battle-create",
                            start_text,
                            (starts_at + timedelta(days=2)).isoformat(),
                            json.dumps({"outcome": "won", "settled_at": start_text}),
                            start_text,
                            start_text,
                        ),
                    )
                    for user_id, role in (
                        ("ascender-private-id", "initiator"),
                        ("helper-private-id", "helper"),
                    ):
                        connection.execute(
                            "INSERT INTO final_battle_members(battle_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) "
                            "VALUES (?, ?, ?, 'released', '{}', ?, ?)",
                            (battle_id, player_ids[user_id], role, start_text, start_text),
                        )
                    # A failed session must never add seasonal cooperation score.
                    connection.execute(
                        "INSERT INTO final_battle_sessions(battle_id, initiator_id, create_operation_id, status, round_no, action_sequence, starts_at, expires_at, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) "
                        "VALUES ('season-coop-failed', ?, 'season-battle-failed', 'settled', 3, 8, ?, ?, '{}', '{}', ?, 'content-0.6', 'combat-0.6.1', ?, ?)",
                        (
                            player_ids["remainer-private-id"],
                            start_text,
                            (starts_at + timedelta(days=3)).isoformat(),
                            json.dumps({"outcome": "lost", "settled_at": start_text}),
                            start_text,
                            start_text,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO final_battle_members(battle_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) "
                        "VALUES ('season-coop-failed', ?, 'initiator', 'released', '{}', ?, ?)",
                        (player_ids["remainer-private-id"], start_text, start_text),
                    )

            seed_records()
            qq_actor = replace(qq, user_id="ascender-private-id", operation_id="qq-season-open")
            open_board = await runtime.adapters.dispatch(
                "qq.official", qq_actor, "终局赛季 飞升榜"
            )
            assert open_board.code == "FINAL_SEASON_RANKING"
            assert open_board.data["status"] == "collecting"
            assert open_board.data["standings"][0]["score"] == 1000
            assert open_board.data["personal_standings"][0]["rank"] == 1
            public = json.dumps(open_board.data, ensure_ascii=False)
            assert "ascender-private-id" not in public
            assert "隐私道号" not in public
            assert "qq-event-user" not in public

            clock.value = ends_at
            frozen = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, user_id="remainer-private-id", operation_id="ob-season-freeze"),
                f"终局赛季 {season_id}",
            )
            assert frozen.data["status"] == "frozen"
            assert frozen.data["frozen_at"] == ends_at.isoformat()
            boards = {entry["board_key"] for entry in frozen.data["standings"]}
            assert boards == {"ascension", "dao", "cooperation"}
            cooperation_rows = [
                entry for entry in frozen.data["standings"] if entry["board_key"] == "cooperation"
            ]
            assert len(cooperation_rows) == 2
            assert all(entry["score"] == 50 for entry in cooperation_rows)
            full_public = json.dumps(frozen.data, ensure_ascii=False)
            for private_id, _, _ in actors:
                assert private_id not in full_public
            with sqlite3.connect(runtime.settings.database_path) as connection:
                member_ids = dict(
                    connection.execute(
                        "SELECT platform_user_id, id FROM players WHERE platform_user_id IN (?, ?)",
                        ("ascender-private-id", "helper-private-id"),
                    ).fetchall()
                )
                actual_tie_order = [
                    row[0]
                    for row in connection.execute(
                        "SELECT p.platform_user_id FROM final_heaven_rankings r "
                        "JOIN players p ON p.id = r.player_id "
                        "WHERE r.season_id = ? AND r.board_key = 'cooperation' ORDER BY r.rank",
                        (season_id,),
                    ).fetchall()
                ]
            expected_tie_order = sorted(
                member_ids,
                key=lambda user_id: final_heaven_tie_breaker(season_id, member_ids[user_id]),
            )
            assert actual_tie_order == expected_tie_order
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE endgame_endings SET created_at = ? WHERE operation_id = 'ending-a'",
                    ((ends_at + timedelta(seconds=1)).isoformat(),),
                )
                connection.execute("DELETE FROM final_battle_sessions WHERE battle_id = 'season-coop-success'")
                frozen_snapshot = connection.execute(
                    "SELECT snapshot_json FROM final_heaven_seasons WHERE season_id = ?",
                    (season_id,),
                ).fetchone()[0]
            assert "ascender-private-id" not in frozen_snapshot
            replay_frozen = await runtime.adapters.dispatch(
                "qq.official",
                replace(qq, user_id="ascender-private-id", operation_id="qq-season-replay"),
                f"终局赛季 {season_id}",
            )
            assert replay_frozen.data["standings"] == frozen.data["standings"]

            claim_context = replace(qq, user_id="ascender-private-id", operation_id="qq-season-claim")
            claim = await runtime.adapters.dispatch(
                "qq.official", claim_context, f"领取终局赛季奖励 {season_id}"
            )
            assert claim.code == "FINAL_RANKING_REWARD_CLAIMED"
            assert set(claim.data["title_keys"]) == {
                "title.season.final_heaven.ascension",
                "title.season.final_heaven.cooperation",
            }
            assert claim.data["entitlements"] == ["chapter.final_heaven"]
            honor_status = await runtime.adapters.dispatch(
                "qq.official",
                replace(claim_context, operation_id="qq-season-honor-status"),
                "\u529f\u4e1a\u5f55",
            )
            assert honor_status.ok
            replay = await runtime.adapters.dispatch(
                "qq.official", claim_context, f"领取终局赛季奖励 {season_id}"
            )
            assert replay.data["idempotent_replay"] is True
            duplicate = await runtime.adapters.dispatch(
                "qq.official",
                replace(claim_context, operation_id="qq-season-claim-again"),
                f"领取终局赛季奖励 {season_id}",
            )
            assert duplicate.code == "FINAL_RANKING_REWARD_CLAIMED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                titles = connection.execute(
                    "SELECT title_key FROM honor_titles WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    ("ascender-private-id",),
                ).fetchall()
                entitlement_count = connection.execute(
                    "SELECT COUNT(*) FROM final_heaven_entitlements WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    ("ascender-private-id",),
                ).fetchone()[0]
            seasonal_titles = {
                value[0] for value in titles if value[0].startswith("title.season.final_heaven.")
            }
            assert seasonal_titles == set(claim.data["title_keys"])
            assert entitlement_count == 1
            await runtime.close()

    asyncio.run(run())


def test_final_heaven_expired_claim_auto_grants_titles_but_not_chapter_entitlement() -> None:
    async def run() -> None:
        initial = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)
        _, starts_at, ends_at = final_heaven_season_window(initial)
        qq, _ = _adapter_contexts()
        clock = MutableClock(starts_at + timedelta(days=2))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user_id = "expired-qq-private"
            actor = replace(qq, user_id=user_id, operation_id="expired-create")
            assert (await runtime.adapters.dispatch(actor.adapter, actor, "\u5f00\u59cb\u4fee\u4ed9")).ok
            assert (
                await runtime.adapters.dispatch(
                    actor.adapter,
                    replace(actor, operation_id="expired-seek"),
                    "\u5bfb\u4ed9\u95ee\u9053",
                )
            ).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user_id,)
                ).fetchone()[0]
                completed_at = (starts_at + timedelta(days=1)).isoformat()
                connection.execute(
                    "INSERT INTO endgame_endings(player_id, ending_key, status, snapshot_json, operation_id, content_version, rule_version, created_at) "
                    "VALUES (?, 'ascend', 'ascended', '{}', 'expired-ending', 'content-0.6', 'progression-0.6.1', ?)",
                    (player_id, completed_at),
                )
            clock.value = ends_at + timedelta(days=7)
            context = replace(actor, operation_id="expired-first-view")
            status = await runtime.adapters.dispatch(
                "qq.official", context, "\u7ec8\u5c40\u8d5b\u5b63"
            )
            assert status.data["status"] == "collecting"
            assert status.data["season_id"] != final_heaven_season_window(initial)[0]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                old_season_status = connection.execute(
                    "SELECT status FROM final_heaven_seasons WHERE season_id = ?",
                    (final_heaven_season_window(initial)[0],),
                ).fetchone()[0]
                title_count = connection.execute(
                    "SELECT COUNT(*) FROM honor_titles WHERE player_id = ? AND title_key = 'title.season.final_heaven.ascension'",
                    (player_id,),
                ).fetchone()[0]
                entitlement_count = connection.execute(
                    "SELECT COUNT(*) FROM final_heaven_entitlements WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0]
                auto_grant_operations = connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_name = 'event.final_heaven.auto_grant' AND player_id = ?",
                    (player_id,),
                ).fetchone()[0]
            assert title_count == 1
            assert entitlement_count == 0
            assert old_season_status == "frozen"
            assert auto_grant_operations == 1
            expired_context = replace(actor, operation_id="expired-claim")
            expired = await runtime.adapters.dispatch(
                "qq.official",
                expired_context,
                f"\u9886\u53d6\u7ec8\u5c40\u8d5b\u5b63\u5956\u52b1 {final_heaven_season_window(initial)[0]}",
            )
            assert expired.code == "FINAL_RANKING_CLAIM_EXPIRED"
            replay = await runtime.adapters.dispatch(
                "qq.official",
                expired_context,
                f"\u9886\u53d6\u7ec8\u5c40\u8d5b\u5b63\u5956\u52b1 {final_heaven_season_window(initial)[0]}",
            )
            assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())
