from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


def test_three_realms_mainline_is_player_reachable_on_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user, lane, faction in (
                ("qq.official", "three-qq", "调停", "xuantian"),
                ("onebot.v11", "three-onebot", "契约", "demon"),
            ):
                assert (await runtime.dispatch(_context(adapter, user, f"create-{adapter}"), "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                for stage in range(1, 6):
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"start-{adapter}-{stage}"),
                        f"开始三界主线 {lane} {stage}",
                    )
                    assert started.code == "THREE_REALMS_STAGE_STARTED"
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"claim-{adapter}-{stage}"),
                        f"领取三界主线奖励 {lane} {stage}",
                    )
                    assert claimed.code == "THREE_REALMS_STAGE_CLAIMED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"claim-{adapter}-5"),
                    f"领取三界主线奖励 {lane} 5",
                )
                assert replay.code == "THREE_REALMS_STAGE_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                other_lane = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"other-{adapter}"),
                    "开始三界主线 共生 1",
                )
                assert other_lane.code == "THREE_REALMS_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    row = db.execute(
                        "SELECT intro_json, faction_reputation_json, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert "story.mainline.three_realms" in json.loads(row[0])["flags"]
                    assert json.loads(row[1])[faction] == 1000
                    assert json.loads(row[2])["item.token.rebuild_path"] == 1
                    assert db.execute(
                        "SELECT COUNT(*) FROM quest_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND quest_key='story.mainline.three_realms'",
                        (adapter, user),
                    ).fetchone()[0] == 5
                    assert db.execute(
                        "SELECT status FROM quest_progress WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND quest_key='story.mainline.three_realms'",
                        (adapter, user),
                    ).fetchone()[0] == "completed"
            await runtime.close()

    asyncio.run(run())

