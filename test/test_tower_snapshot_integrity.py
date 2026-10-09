from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.runtime import create_runtime

from test_tower import _enter_tower_eligible_path, _send


def test_mist_trial_tower_reward_and_operation_snapshots_are_strict_on_both_adapters() -> None:
    async def run() -> None:
        malformed_rewards = (
            '{"spirit_stones":10,"spirit_stones":9999}',
            '{"spirit_stones":',
            '[]',
            '{"spirit_stones":true}',
            '{"spirit_stones":"10"}',
            '{"spirit_stones":-1}',
            '{"spirit_stones":9999}',
        )
        replay_cases: list[tuple[str, str, str]] = []
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"tower-integrity-{adapter.replace('.', '-')}"
                await _enter_tower_eligible_path(runtime, adapter, user, user)
                start_operation = f"{user}-challenge"
                challenged = await _send(
                    runtime, adapter, user, start_operation, "挑战试炼塔 1"
                )
                assert challenged.code == "TOWER_CHALLENGE_SETTLED"
                claim_operation = f"{user}-claim-0"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id, run_id, valid_reward = connection.execute(
                        "SELECT p.id, r.run_id, r.reward_json "
                        "FROM players p JOIN tower_runs r ON r.player_id=p.id "
                        "WHERE p.platform=? AND p.platform_user_id=? "
                        "ORDER BY r.id DESC LIMIT 1",
                        (adapter, user),
                    ).fetchone()
                    player_before = connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()
                    stored_start = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (start_operation,),
                    ).fetchone()[0]
                    start_payload = json.loads(stored_start)
                    start_payload["floor_no"] = 2
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(start_payload, ensure_ascii=False), start_operation),
                    )

                tampered_start = await _send(
                    runtime, adapter, user, start_operation, "挑战试炼塔 1"
                )
                assert tampered_start.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone() == player_before
                    assert connection.execute(
                        "SELECT status FROM tower_runs WHERE run_id=?", (run_id,)
                    ).fetchone()[0] == "reward_pending"
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_start, start_operation),
                    )

                for index, malformed in enumerate(malformed_rewards):
                    operation_id = f"{user}-claim-{index}"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE tower_runs SET reward_json=? WHERE run_id=?",
                            (malformed, run_id),
                        )
                    failed = await _send(
                        runtime, adapter, user, operation_id, "领取试炼塔奖励"
                    )
                    assert failed.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                            (player_id,),
                        ).fetchone() == player_before
                        assert connection.execute(
                            "SELECT status FROM tower_runs WHERE run_id=?", (run_id,)
                        ).fetchone()[0] == "reward_pending"
                        assert connection.execute(
                            "SELECT COUNT(*) FROM tower_reward_claims WHERE run_id=?", (run_id,)
                        ).fetchone()[0] == 0
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                        ).fetchone()[0] == 0

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE tower_runs SET reward_json=? WHERE run_id=?",
                        (valid_reward, run_id),
                    )
                settled = await _send(
                    runtime, adapter, user, claim_operation, "领取试炼塔奖励"
                )
                assert settled.code == "TOWER_REWARD_CLAIMED"
                assert settled.data["reward"] == json.loads(valid_reward)

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stored_claim = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (claim_operation,),
                    ).fetchone()[0]
                    player_after_claim = connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()
                    valid_claim_reward = connection.execute(
                        "SELECT reward_json FROM tower_reward_claims WHERE run_id=?", (run_id,)
                    ).fetchone()[0]
                    payload = json.loads(stored_claim)
                    payload["reward"]["spirit_stones"] = 9999
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(payload, ensure_ascii=False), claim_operation),
                    )

                tampered_claim = await _send(
                    runtime, adapter, user, claim_operation, "领取试炼塔奖励"
                )
                assert tampered_claim.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone() == player_after_claim
                    assert connection.execute(
                        "SELECT COUNT(*) FROM tower_reward_claims WHERE run_id=?", (run_id,)
                    ).fetchone()[0] == 1
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_claim, claim_operation),
                    )
                    corrupted_operation = stored_claim.replace(
                        '"reward":', '"reward":{},"reward":', 1
                    )
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (corrupted_operation, claim_operation),
                    )

                duplicate_claim = await _send(
                    runtime, adapter, user, claim_operation, "领取试炼塔奖励"
                )
                assert duplicate_claim.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone() == player_after_claim
                    assert connection.execute(
                        "SELECT COUNT(*) FROM tower_reward_claims WHERE run_id=?", (run_id,)
                    ).fetchone()[0] == 1
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_claim, claim_operation),
                    )
                    connection.execute(
                        "UPDATE tower_reward_claims SET reward_json=? WHERE run_id=?",
                        ('{"spirit_stones":9999}', run_id),
                    )

                corrupted_ledger = await _send(
                    runtime, adapter, user, claim_operation, "领取试炼塔奖励"
                )
                assert corrupted_ledger.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json, stamina FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone() == player_after_claim
                    connection.execute(
                        "UPDATE tower_reward_claims SET reward_json=? WHERE run_id=?",
                        (valid_claim_reward, run_id),
                    )

                replay = await _send(
                    runtime, adapter, user, claim_operation, "领取试炼塔奖励"
                )
                assert replay.code == "TOWER_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                replay_cases.append((adapter, user, claim_operation))

            await runtime.close()
            restarted = create_runtime(data_dir=data_dir)
            for adapter, user, operation_id in replay_cases:
                replay = await _send(
                    restarted, adapter, user, operation_id, "领取试炼塔奖励"
                )
                assert replay.code == "TOWER_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
            await restarted.close()

    asyncio.run(run())
