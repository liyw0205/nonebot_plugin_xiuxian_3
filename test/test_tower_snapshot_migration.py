from __future__ import annotations

import asyncio
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.tower_migration import ensure_tower_schema
from nonebot_plugin_xiuxian_3.xiuxian.specials.tower_rules import reward_snapshot_digest

from test_tower import _enter_tower_eligible_path, _send


FLOOR_ONE_REWARD = {"spirit_stones": 10, "item.mat.array_sand": 1}


def _latest_run(database_path: str, adapter: str, user: str) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT r.id, r.run_id, r.status, r.reward_json, r.reward_maximums_json, r.reward_digest, "
            "p.id AS player_id "
            "FROM tower_runs r JOIN players p ON p.id=r.player_id "
            "WHERE p.platform=? AND p.platform_user_id=? ORDER BY r.id DESC LIMIT 1",
            (adapter, user),
        ).fetchone()
        return dict(row)


def _player_state(database_path: str, player_id: int) -> tuple[object, ...]:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT p.spirit_stones, p.stamina, p.cultivation, p.inventory_json, "
            "COALESCE(r.local_json, '{}') "
            "FROM players p LEFT JOIN player_reputations r ON r.player_id=p.id WHERE p.id=?",
            (player_id,),
        ).fetchone()


def _ledger_sizes(database_path: str) -> tuple[int, int]:
    with sqlite3.connect(database_path) as connection:
        return (
            int(connection.execute("SELECT COUNT(*) FROM tower_reward_claims").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]),
        )


def _update_run(database_path: str, run_id: str, **columns: str) -> None:
    assignments = ", ".join(f"{name}=?" for name in columns)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"UPDATE tower_runs SET {assignments} WHERE run_id=?",
            (*columns.values(), run_id),
        )


def _set_digest(database_path: str, run_id: str, reward: dict[str, int], maximums: dict[str, int]) -> None:
    _update_run(
        database_path, run_id, reward_digest=reward_snapshot_digest(reward, maximums)
    )


def _assert_no_write(database_path, player_id, state, ledger) -> None:
    assert _player_state(database_path, player_id) == state
    assert _ledger_sizes(database_path) == ledger


async def _reach_reward_pending(data_dir: str, adapter: str, user: str):
    runtime = create_runtime(data_dir=data_dir)
    await _enter_tower_eligible_path(runtime, adapter, user, user)
    challenged = await _send(runtime, adapter, user, f"{user}-challenge", "挑战试炼塔 1")
    assert challenged.code == "TOWER_CHALLENGE_SETTLED", (challenged.code, challenged.message)
    return runtime


def test_legacy_reward_digest_backfill_keeps_pending_claim_and_replay_stable() -> None:
    async def run() -> None:
        adapter, user = "onebot.v11", "tower-digest-legacy"
        with TemporaryDirectory() as data_dir:
            runtime = await _reach_reward_pending(data_dir, adapter, user)
            database = str(runtime.settings.database_path)
            run_row = _latest_run(database, adapter, user)
            player_id = int(run_row["player_id"])
            assert run_row["reward_digest"] != ""
            # Simulate a database written before the integrity column existed.
            _update_run(database, str(run_row["run_id"]), reward_digest="")
            await runtime.close()

            tampered_maximums = {"local.qingshi_town": 5}
            reopened = create_runtime(data_dir=data_dir)
            await reopened.initialize()
            assert _latest_run(database, adapter, user)["reward_digest"] != ""

            # The frozen caps must still match the frozen reward keys even when the
            # integrity hash is recomputed for the tampered pair.
            _update_run(
                database,
                str(run_row["run_id"]),
                reward_maximums_json='{"local.qingshi_town":5,"local.qingshi_town":5}',
            )
            broken_caps = await _send(reopened, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert broken_caps.code == "PERSISTENCE_ERROR"
            _set_digest(database, str(run_row["run_id"]), FLOOR_ONE_REWARD, tampered_maximums)
            mismatched_caps = await _send(reopened, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert mismatched_caps.code == "PERSISTENCE_ERROR"
            state = _player_state(database, player_id)
            ledger = _ledger_sizes(database)
            _assert_no_write(database, player_id, state, ledger)

            # Restoring the frozen reward/caps pair re-opens the same claim operation.
            _update_run(
                database,
                str(run_row["run_id"]),
                reward_maximums_json="{}",
                reward_digest=reward_snapshot_digest(FLOOR_ONE_REWARD, {}),
            )
            restored = await _send(reopened, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert restored.code == "TOWER_REWARD_CLAIMED", (restored.code, restored.message)
            assert restored.data["reward"] == FLOOR_ONE_REWARD
            assert _latest_run(database, adapter, user)["status"] == "claimed"
            assert _ledger_sizes(database) == (ledger[0] + 1, ledger[1] + 1)
            after_claim = _player_state(database, player_id)
            assert after_claim != state
            await reopened.close()

            # A claimed run must stay replayable across an upgrade of the same row.
            _update_run(database, str(run_row["run_id"]), reward_digest="")
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            assert _latest_run(database, adapter, user)["reward_digest"] != ""
            replay = await _send(runtime, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert replay.code == "TOWER_REWARD_CLAIMED", (replay.code, replay.message)
            assert replay.data["idempotent_replay"] is True
            assert replay.data["reward"] == FLOOR_ONE_REWARD
            _assert_no_write(database, player_id, after_claim, (ledger[0] + 1, ledger[1] + 1))
            await runtime.close()

    asyncio.run(run())


def test_unreadable_legacy_reward_stays_rejected_until_repaired() -> None:
    async def run() -> None:
        adapter, user = "qq.official", "tower-digest-corrupt"
        with TemporaryDirectory() as data_dir:
            runtime = await _reach_reward_pending(data_dir, adapter, user)
            database = str(runtime.settings.database_path)
            run_row = _latest_run(database, adapter, user)
            player_id = int(run_row["player_id"])
            stored_reward = str(run_row["reward_json"])
            _update_run(
                database,
                str(run_row["run_id"]),
                reward_json='{"spirit_stones":10,"spirit_stones":9999}',
                reward_digest="",
            )
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            # A duplicate-key legacy snapshot must not gain a digest by laundering
            # the surviving value through the migration.
            assert _latest_run(database, adapter, user)["reward_digest"] == ""
            state = _player_state(database, player_id)
            ledger = _ledger_sizes(database)
            rejected = await _send(runtime, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert rejected.code == "PERSISTENCE_ERROR"
            _assert_no_write(database, player_id, state, ledger)

            _update_run(database, str(run_row["run_id"]), reward_json=stored_reward)
            repaired = await _send(runtime, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert repaired.code == "PERSISTENCE_ERROR"
            _assert_no_write(database, player_id, state, ledger)
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            claimed = await _send(runtime, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert claimed.code == "TOWER_REWARD_CLAIMED", (claimed.code, claimed.message)
            assert claimed.data["reward"] == FLOOR_ONE_REWARD
            assert _ledger_sizes(database) == (ledger[0] + 1, ledger[1] + 1)
            after_claim = _player_state(database, player_id)

            # Rewriting only the claim ledger keeps the frozen run reward authoritative.
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE tower_reward_claims SET reward_json=? WHERE run_id=?",
                    ('{"spirit_stones":9999}', run_row["run_id"]),
                )
            inflated = await _send(runtime, adapter, user, f"{user}-claim", "领取试炼塔奖励")
            assert inflated.code == "PERSISTENCE_ERROR"
            _assert_no_write(database, player_id, after_claim, (ledger[0] + 1, ledger[1] + 1))
            await runtime.close()

    asyncio.run(run())


def test_reward_snapshot_digest_backfill_is_idempotent() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE players(id INTEGER PRIMARY KEY)")
        for player_id in (1, 2, 3):
            connection.execute("INSERT INTO players(id) VALUES (?)", (player_id,))
        ensure_tower_schema(connection)
        ensure_tower_schema(connection)
        connection.execute(
            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
            "starts_at,reward_json,reward_maximums_json,reward_digest,created_at,updated_at) "
            "VALUES ('legacy-pending',1,'tower.mist_trial',1,'reward_pending',1,"
            "'2026-10-09T00:00:00','{\"spirit_stones\":10}','{}','','2026-10-09T00:00:00','2026-10-09T00:00:00')"
        )
        connection.execute(
            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
            "starts_at,reward_json,reward_maximums_json,reward_digest,created_at,updated_at) "
            "VALUES ('legacy-lost',2,'tower.mist_trial',2,'lost',0,"
            "'2026-10-09T00:00:00','{}','{}','','2026-10-09T00:00:00','2026-10-09T00:00:00')"
        )
        connection.execute(
            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
            "starts_at,reward_json,reward_maximums_json,reward_digest,created_at,updated_at) "
            "VALUES ('legacy-tampered',3,'tower.mist_trial',3,'reward_pending',1,"
            "'2026-10-09T00:00:00','{\"spirit_stones\":10,\"spirit_stones\":9999}','{}','','2026-10-09T00:00:00','2026-10-09T00:00:00')"
        )

        ensure_tower_schema(connection)
        digests = dict(
            connection.execute("SELECT run_id, reward_digest FROM tower_runs").fetchall()
        )
        assert digests["legacy-pending"] == reward_snapshot_digest({"spirit_stones": 10}, {})
        assert digests["legacy-lost"] == reward_snapshot_digest({}, {})
        assert digests["legacy-tampered"] == ""

        ensure_tower_schema(connection)
        assert dict(
            connection.execute("SELECT run_id, reward_digest FROM tower_runs").fetchall()
        ) == digests
