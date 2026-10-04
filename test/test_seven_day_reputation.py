from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    context = CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)
    return await runtime.adapters.dispatch(adapter, context, command)


async def _start_campaign(runtime, adapter: str, user: str, prefix: str, *, enter_path: bool) -> None:
    for index, command in enumerate(("开始修仙", "寻仙问道")):
        result = await _send(runtime, adapter, user, f"{prefix}-start-{index}", command)
        assert result.ok, (command, result.code, result.message)
    status = await _send(runtime, adapter, user, f"{prefix}-status", "七日入道")
    assert status.code == "SEVEN_DAY_STATUS"
    if not enter_path:
        return
    for index, command in enumerate(
        (
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await _send(runtime, adapter, user, f"{prefix}-path-{index}", command)
        assert result.ok, (command, result.code, result.message)


def _set_reputation(runtime, adapter: str, user: str, value: int | str) -> None:
    local_json = value if isinstance(value, str) else json.dumps(
        {"local.xuantian.new_town": value}, sort_keys=True
    )
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
            "VALUES(?,?,0,'test') ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, local_json),
        )


def _player_state(runtime, adapter: str, user: str) -> tuple[str, str, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT r.local_json,p.inventory_json, "
            "(SELECT COUNT(*) FROM seven_day_goal_claims c WHERE c.player_id=p.id) "
            "FROM players p LEFT JOIN player_reputations r ON r.player_id=p.id "
            "WHERE p.platform=? AND p.platform_user_id=?",
            (adapter, user),
        ).fetchone()
    return str(row[0] or "{}"), str(row[1]), int(row[2])


def _set_town_reputation_cap(data_dir: Path, cap: int) -> None:
    path = data_dir / "地图" / "地点.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    town = next(row for row in document["records"] if row["key"] == "xuantian.new_town")
    town["local_reputation_maximum"] = cap
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_seven_day_reputation_uses_location_cap_and_shared_reward_transaction() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _set_town_reputation_cap(data_dir, 6)
            runtime = create_runtime(
                data_dir=data_dir,
                adapters=("qq.official", "onebot.v11"),
                clock=clock,
            )
            users = {
                "d4_qq": ("qq.official", "seven-d4-qq", False),
                "d4_ob": ("onebot.v11", "seven-d4-ob", False),
                "d7_qq": ("qq.official", "seven-d7-qq", True),
                "d7_ob": ("onebot.v11", "seven-d7-ob", True),
                "d7_retry": ("onebot.v11", "seven-d7-retry", True),
            }
            try:
                for name, (adapter, user, enter_path) in users.items():
                    await _start_campaign(runtime, adapter, user, name, enter_path=enter_path)

                _set_reputation(runtime, "qq.official", "seven-d4-qq", 5)
                _set_reputation(runtime, "onebot.v11", "seven-d4-ob", 10)
                _set_reputation(runtime, "qq.official", "seven-d7-qq", 0)
                _set_reputation(runtime, "onebot.v11", "seven-d7-ob", 5)

                clock.advance(days=3)
                for name in ("d4_qq", "d4_ob"):
                    adapter, user, _ = users[name]
                    accepted = await _send(
                        runtime, adapter, user, f"{name}-bounty", "接取悬赏 草药补给"
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    claim = await _send(
                        runtime, adapter, user, f"{name}-claim", "领取七日目标 4"
                    )
                    assert claim.code == "SEVEN_DAY_GOAL_CLAIMED"
                    assert claim.data["reward"]["local_reputation"] == (
                        1 if name == "d4_qq" else 0
                    )
                    if name == "d4_qq":
                        replay = await _send(
                            runtime, adapter, user, f"{name}-claim", "领取七日目标 4"
                        )
                        assert replay.data["idempotent_replay"] is True
                        conflict = await _send(
                            runtime, adapter, user, f"{name}-claim", "领取七日目标 5"
                        )
                        assert conflict.code == "OPERATION_CONFLICT"
                        duplicate = await _send(
                            runtime, adapter, user, f"{name}-claim-again", "领取七日目标 4"
                        )
                        assert duplicate.code == "SEVEN_DAY_ALREADY_CLAIMED"

                clock.advance(days=3)
                for name in ("d7_qq", "d7_ob"):
                    adapter, user, _ = users[name]
                    claim = await _send(
                        runtime, adapter, user, f"{name}-claim", "领取七日目标 7"
                    )
                    assert claim.code == "SEVEN_DAY_GOAL_CLAIMED"
                    assert claim.data["reward"]["local_reputation"] == (
                        5 if name == "d7_qq" else 1
                    )

                _set_reputation(runtime, "onebot.v11", "seven-d7-retry", "{")
                before_bad_json = _player_state(runtime, "onebot.v11", "seven-d7-retry")
                bad_json = await _send(
                    runtime, "onebot.v11", "seven-d7-retry", "ob-d7-retry", "领取七日目标 7"
                )
                assert bad_json.code == "PERSISTENCE_ERROR"
                assert _player_state(runtime, "onebot.v11", "seven-d7-retry") == before_bad_json

                _set_reputation(runtime, "onebot.v11", "seven-d7-retry", 4)
                before_fault = _player_state(runtime, "onebot.v11", "seven-d7-retry")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_seven_day_operation BEFORE INSERT ON operations "
                        "WHEN NEW.operation_id='ob-d7-retry' BEGIN "
                        "SELECT RAISE(ABORT, 'injected operation ledger failure'); END"
                    )
                failed_commit = await _send(
                    runtime, "onebot.v11", "seven-d7-retry", "ob-d7-retry", "领取七日目标 7"
                )
                assert failed_commit.code == "PERSISTENCE_ERROR"
                assert _player_state(runtime, "onebot.v11", "seven-d7-retry") == before_fault
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("DROP TRIGGER fail_seven_day_operation")

                retried = await _send(
                    runtime, "onebot.v11", "seven-d7-retry", "ob-d7-retry", "领取七日目标 7"
                )
                assert retried.code == "SEVEN_DAY_GOAL_CLAIMED"
                assert retried.data["reward"] == {
                    "item.ticket.fate_basic": 2,
                    "local_reputation": 2,
                }
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    reputation, inventory = connection.execute(
                        "SELECT r.local_json,p.inventory_json FROM players p "
                        "JOIN player_reputations r ON r.player_id=p.id "
                        "WHERE p.platform=? AND p.platform_user_id=?",
                        ("onebot.v11", "seven-d7-retry"),
                    ).fetchone()
                    operation_count = connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id='ob-d7-retry'"
                    ).fetchone()[0]
                assert json.loads(reputation) == {"local.xuantian.new_town": 6}
                assert json.loads(inventory)["item.ticket.fate_basic"] == 2
                assert operation_count == 1

                await runtime.close()
                _set_town_reputation_cap(data_dir, 20)
                recovered = create_runtime(
                    data_dir=data_dir,
                    adapters=("onebot.v11",),
                    clock=clock,
                )
                try:
                    replay = await _send(
                        recovered,
                        "onebot.v11",
                        "seven-d7-retry",
                        "ob-d7-retry",
                        "领取七日目标 7",
                    )
                    assert replay.code == "SEVEN_DAY_GOAL_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"]["local_reputation"] == 2
                    assert _player_state(
                        recovered, "onebot.v11", "seven-d7-retry"
                    )[2] == before_fault[2] + 1
                finally:
                    await recovered.close()
            finally:
                if not runtime._closed:
                    await runtime.close()

    asyncio.run(run())
