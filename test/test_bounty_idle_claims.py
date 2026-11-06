from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _claimed_assignment(
    database_path,
    player_id: int,
    *,
    assignment_id: str,
    route_key: str,
    now: datetime,
) -> None:
    text = now.isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO idle_assignments(assignment_id, player_id, operation_id, route_key, "
            "status, business_date, starts_at, claim_at, max_claim_at, cancel_until, "
            "cost_json, snapshot_json, result_json, claim_operation_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?, ?, ?, '{}', '{}', '{}', ?, ?, ?)",
            (
                assignment_id,
                player_id,
                f"op-{assignment_id}",
                route_key,
                now.date().isoformat(),
                text,
                text,
                (now + timedelta(hours=24)).isoformat(),
                (now + timedelta(seconds=60)).isoformat(),
                f"claim-{assignment_id}",
                text,
                text,
            ),
        )


def test_idle_claims_bounty_requires_a_claim_since_acceptance() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "bounty-idle-claims"
            created = await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")
            assert created.ok, created.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='foundation', "
                    "realm_layer=4 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            _claimed_assignment(
                runtime.settings.database_path,
                player_id,
                assignment_id="idle-before-accept",
                route_key="idle.cloud_mine_watch",
                now=clock.value - timedelta(hours=1),
            )

            accepted = await runtime.dispatch(
                _context(adapter, user, "accept", "bounty-idle-accept"),
                "接取悬赏 矿区看守差事",
            )
            assert accepted.code == "BOUNTY_ACCEPTED", accepted.message
            assert accepted.data["bounty_key"] == "bounty.idle.mine_watch"
            assert accepted.data["progress"] == 0

            incomplete = await runtime.dispatch(
                _context(adapter, user, "claim-early", "bounty-idle-claim"),
                "领取悬赏",
            )
            assert incomplete.code == "BOUNTY_NOT_COMPLETE", incomplete.message

            clock.value = clock.value + timedelta(hours=6)
            _claimed_assignment(
                runtime.settings.database_path,
                player_id,
                assignment_id="idle-after-accept",
                route_key="idle.cloud_mine_watch",
                now=clock.value,
            )

            claimed = await runtime.dispatch(
                _context(adapter, user, "claim", "bounty-idle-claim"),
                "领取悬赏",
            )
            assert claimed.code == "BOUNTY_CLAIMED", claimed.message
            assert claimed.data["bounty_key"] == "bounty.idle.mine_watch"
            assert claimed.data["progress"] == 1
            assert claimed.data["target"] == 1
            assert claimed.data["rewards"]

            replay = await runtime.dispatch(
                _context(adapter, user, "claim-replay", "bounty-idle-claim"),
                "领取悬赏",
            )
            assert replay.code == "BOUNTY_CLAIMED", replay.message
            assert replay.data["idempotent_replay"] is True
            assert replay.data["rewards"] == claimed.data["rewards"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, progress = connection.execute(
                    "SELECT status, json_extract(snapshot_json, '$.baseline_idle_assignment_ids') "
                    "FROM bounty_offers WHERE player_id=? ORDER BY id DESC LIMIT 1",
                    (player_id,),
                ).fetchone()
            assert status == "claimed"
            assert "idle-before-accept" in progress
            assert "idle-after-accept" not in progress
            await runtime.close()

    asyncio.run(run())
