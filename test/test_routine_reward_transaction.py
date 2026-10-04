from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.routine.rules import redemption_code_definition


ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _set_local_reputation(database_path: Path, adapter: str, user: str, value: object) -> None:
    with sqlite3.connect(database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, ?, 0, 'test')
            ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json
            """,
            (player_id, value if isinstance(value, str) else json.dumps(value)),
        )


def _set_new_town_cap(data_dir: Path, maximum: int) -> None:
    location_file = data_dir / "地图" / "地点.json"
    document = json.loads(location_file.read_text(encoding="utf-8"))
    location = next(row for row in document["records"] if row["key"] == "xuantian.new_town")
    location["local_reputation_maximum"] = maximum
    location_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_routine_rewards_share_caps_replay_and_adapter_paths() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _set_new_town_cap(data_dir, 4)
            code = redemption_code_definition(
                "code.routine.reward.transaction",
                "REWARD-TRANSACTION",
                {
                    "spirit_stones": 7,
                    "energy": 3,
                    "local_reputation": 5,
                    "service_reputation": 3,
                },
            )
            settings = XiuxianSettings(data_dir=data_dir, redemption_codes=(code,))
            runtime = create_runtime(settings=settings, adapters=ADAPTERS)
            users = {adapter: f"routine-reward-{adapter}" for adapter in ADAPTERS}
            try:
                invalid_user = "routine-reward-invalid"
                assert (
                    await runtime.adapters.dispatch(
                        "qq.official",
                        _context("qq.official", invalid_user, "invalid-create"),
                        "开始修仙",
                    )
                ).ok
                assert (
                    await runtime.adapters.dispatch(
                        "qq.official",
                        _context("qq.official", invalid_user, "invalid-checkin"),
                        "道历问安",
                    )
                ).ok
                _set_local_reputation(
                    runtime.settings.database_path,
                    "qq.official",
                    invalid_user,
                    "{",
                )
                invalid = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", invalid_user, "invalid-achievement"),
                    "领取功业 1",
                )
                assert invalid.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    invalid_player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        ("qq.official", invalid_user),
                    ).fetchone()[0]
                    assert connection.execute(
                        "SELECT 1 FROM achievement_claims WHERE player_id=? AND achievement_key=?",
                        (invalid_player_id, "achievement.first_checkin"),
                    ).fetchone() is None
                _set_local_reputation(
                    runtime.settings.database_path,
                    "qq.official",
                    invalid_user,
                    {},
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        CREATE TRIGGER injected_routine_operation_failure
                        BEFORE INSERT ON operations
                        WHEN NEW.operation_id = 'invalid-achievement'
                        BEGIN SELECT RAISE(ABORT, 'injected routine operation failure'); END
                        """
                    )
                operation_failed = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", invalid_user, "invalid-achievement"),
                    "领取功业 1",
                )
                assert operation_failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("DROP TRIGGER injected_routine_operation_failure")
                retried = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", invalid_user, "invalid-achievement"),
                    "领取功业 1",
                )
                assert retried.code == "ACHIEVEMENT_CLAIMED"

                for adapter in ADAPTERS:
                    user = users[adapter]
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙"
                        )
                    ).ok
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{adapter}-checkin"), "道历问安"
                        )
                    ).ok
                    _set_local_reputation(runtime.settings.database_path, adapter, user, {"local.xuantian.new_town": 3})

                    claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-achievement"),
                        "领取功业 1",
                    )
                    assert claim.code == "ACHIEVEMENT_CLAIMED"
                    assert claim.data["reward"] == {"local_reputation": 1}
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-achievement"),
                        "领取功业 1",
                    )
                    assert replay.data["idempotent_replay"] is True
                    conflict = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-achievement"),
                        "领取功业 2",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"

                    redeemed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-code"),
                        "兑换密令 reward-transaction",
                    )
                    assert redeemed.code == "REDEMPTION_CODE_CLAIMED"
                    assert redeemed.data["reward"]["spirit_stones"] == 7
                    assert redeemed.data["reward"]["local_reputation"] == 0
                    assert redeemed.data["reward"]["service_reputation"] == 3
                    code_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-code"),
                        "兑换密令 reward-transaction",
                    )
                    assert code_replay.data["idempotent_replay"] is True
                    code_conflict = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-code"),
                        "兑换密令 another-code",
                    )
                    assert code_conflict.code == "OPERATION_CONFLICT"

            finally:
                await runtime.close()

            recovered = create_runtime(settings=settings, adapters=("qq.official",))
            try:
                replay_after_restart = await recovered.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", users["qq.official"], "qq.official-code"),
                    "兑换密令 reward-transaction",
                )
                assert replay_after_restart.data["idempotent_replay"] is True
            finally:
                await recovered.close()

    asyncio.run(run())
