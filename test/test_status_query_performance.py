from __future__ import annotations

import asyncio
import sqlite3

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def test_mainline_evidence_player_indexes_cover_status_reads(tmp_path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path, adapters=("onebot.v11", "qq.official"))
        try:
            for adapter in ("onebot.v11", "qq.official"):
                created = await runtime.adapters.dispatch(
                    adapter,
                    CommandContext(adapter=adapter, user_id=f"status-{adapter}", request_id=f"create-{adapter}"),
                    "开始修仙",
                )
                assert created.ok
                status = await runtime.adapters.dispatch(
                    adapter,
                    CommandContext(adapter=adapter, user_id=f"status-{adapter}", request_id=f"status-{adapter}"),
                    "主线状态",
                )
                assert status.ok

            with sqlite3.connect(runtime.settings.database_path) as connection:
                indexes = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    )
                }
                expected = {
                    "idx_domain_front_participants_player",
                    "idx_domain_front_contributions_player",
                    "idx_domain_front_claims_player",
                }
                assert expected <= indexes
                for table, index in (
                    ("domain_front_participants", "idx_domain_front_participants_player"),
                    ("domain_front_contributions", "idx_domain_front_contributions_player"),
                    ("domain_front_claims", "idx_domain_front_claims_player"),
                ):
                    plan = connection.execute(
                        f"EXPLAIN QUERY PLAN SELECT 1 FROM {table} WHERE player_id = ? LIMIT 1",
                        (1,),
                    ).fetchall()
                    details = " ".join(str(row[3]).upper() for row in plan)
                    assert f"USING COVERING INDEX {index.upper()}" in details
                    assert f"SCAN {table.upper()}" not in details
        finally:
            await runtime.close()

    asyncio.run(run())
