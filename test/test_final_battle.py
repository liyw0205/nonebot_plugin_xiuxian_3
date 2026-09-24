from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _create_player(runtime, adapter: str, user: str, *, leader: bool = False) -> str:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    inventory = {"item.ascension_certificate": 1} if leader else {}
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=?, "
            "endgame_status=?, location_key='tribulation.sky_terrace', path_key='body', "
            "dao_fruit_progress=?, ascension_merit=?, qualification_json=?, inventory_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                10 if leader else 3,
                "tribulation",
                1_000 if leader else 0,
                1_000 if leader else 0,
                json.dumps({"body": 2_000, "agility": 2_000}),
                json.dumps(inventory),
                adapter,
                user,
            ),
        )
        player_id = str(connection.execute(
            "SELECT player_id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0])
        if leader:
            database_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
            ).fetchone()[0]
            for index, key in enumerate(("trial.body_and_mind", "trial.three_realms", "trial.dao_choice")):
                connection.execute(
                    "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'succeeded', 'start', 'end', '{}', 'created', 'updated')",
                    (f"{user}-trial-{index}", database_id, f"{user}-trial-op-{index}", key),
                )
    return player_id


def test_qq_onebot_final_battle_locks_team_settles_once_and_replays_after_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader_adapter, leader = "qq.official", "final-leader"
            leader_id = await _create_player(runtime, leader_adapter, leader, leader=True)
            helpers = []
            for index in range(4):
                adapter = "onebot.v11" if index % 2 == 0 else "qq.official"
                user = f"final-helper-{index}"
                helpers.append((adapter, user, await _create_player(runtime, adapter, user)))

            created = await runtime.adapters.dispatch(leader_adapter, _ctx(leader_adapter, leader, "final-create"), "创建终局战")
            assert created.code == "FINAL_BATTLE_CREATED"
            battle_id = created.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (leader_adapter, leader)
                ).fetchone()[0]) == {}
                assert connection.execute(
                    "SELECT COUNT(*) FROM final_battle_members WHERE battle_id=? AND asset_lock_status='locked'", (battle_id,)
                ).fetchone()[0] == 1

            for index, (adapter, user, _) in enumerate(helpers):
                joined = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"final-join-{index}"), f"加入终局战 {battle_id}")
                assert joined.code == "FINAL_BATTLE_JOINED"
            extra_adapter, extra_user = "onebot.v11", "final-helper-extra"
            await _create_player(runtime, extra_adapter, extra_user)
            full = await runtime.adapters.dispatch(extra_adapter, _ctx(extra_adapter, extra_user, "final-join-full"), f"加入终局战 {battle_id}")
            assert full.code == "FINAL_BATTLE_MEMBER_LIMIT"

            locked = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", helpers[0][1], "final-helper-write"), "开始修炼")
            assert locked.code == "PLAYER_SUSPENDED"
            unauthorized = await runtime.adapters.dispatch(
                helpers[0][0],
                _ctx(helpers[0][0], helpers[0][1], "final-helper-start"),
                f"开始终局战 {battle_id}",
            )
            assert unauthorized.code == "FINAL_BATTLE_PERMISSION_DENIED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT round_no FROM final_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0] == 0

            started = await runtime.adapters.dispatch(leader_adapter, _ctx(leader_adapter, leader, "final-start"), f"开始终局战 {battle_id}")
            assert started.code == "FINAL_BATTLE_CHOICE_REQUIRED"
            invalid_remain = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader, "final-remain-without-fruit"),
                f"选择终局战 留界 {battle_id}",
            )
            assert invalid_remain.code == "ASCENSION_REQUIREMENT_MISSING"
            denied = await runtime.adapters.dispatch(helpers[0][0], _ctx(helpers[0][0], helpers[0][1], "final-helper-choice"), f"选择终局战 留界 {battle_id}")
            assert denied.code == "FINAL_BATTLE_PERMISSION_DENIED"
            started = await runtime.adapters.dispatch(leader_adapter, _ctx(leader_adapter, leader, "final-continue"), f"选择终局战 继续 {battle_id}")
            assert started.code == "FINAL_BATTLE_SETTLED"
            assert started.data["outcome"] == "won"
            assert started.data["debt_delta"] == 0
            assert set(started.data["rewards"]) == {leader_id, *(entry[2] for entry in helpers)}
            assert all(started.data["rewards"][entry[2]]["world_merit"] > 0 for entry in helpers)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM final_battle_rewards WHERE battle_id=?", (battle_id,)
                ).fetchone()[0] == 5
                assert connection.execute(
                    "SELECT COUNT(*) FROM final_battle_members WHERE battle_id=? AND asset_lock_status='locked'", (battle_id,)
                ).fetchone()[0] == 0
                row = connection.execute(
                    "SELECT inventory_json, endgame_status, location_key FROM players WHERE platform=? AND platform_user_id=?",
                    (leader_adapter, leader),
                ).fetchone()
                leader_inventory = json.loads(row[0])
                assert "item.title.ascended" not in leader_inventory
                assert "item.ascension_certificate" not in leader_inventory
                assert (row[1], row[2]) == ("ascension_ready", "ascension.heaven_path")

            ending = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader, "final-ending"),
                "选择结局 飞升",
            )
            assert ending.code == "ENDING_CHOSEN"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (leader_adapter, leader),
                ).fetchone()[0])
                assert inventory["item.title.ascended"] == 1

            replayed = await runtime.adapters.dispatch(leader_adapter, _ctx(leader_adapter, leader, "final-start-replay"), f"开始终局战 {battle_id}")
            assert replayed.code == "FINAL_BATTLE_SETTLED"
            assert replayed.data["rewards"] == started.data["rewards"]
            await runtime.close()

            recovered = create_runtime(data_dir=data_dir)
            replay = await recovered.adapters.dispatch(helpers[0][0], _ctx(helpers[0][0], helpers[0][1], "final-replay-after-restart"), f"终局战回放 {battle_id}")
            assert replay.code == "FINAL_BATTLE_REPLAY"
            assert replay.data["result"]["outcome"] == "won"
            assert replay.data["actions"]
            await recovered.close()

    asyncio.run(run())


def test_onebot_final_battle_remain_choice_records_ending_and_does_not_add_failure_debt() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "final-remain"
            await _create_player(runtime, adapter, user, leader=True)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET dao_fruit_key='fruit.immortal_body' WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "remain-create"), "创建终局战")
            battle_id = created.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM final_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0])
                snapshot["enemy"]["max_hp"] = 500
                connection.execute(
                    "UPDATE final_battle_sessions SET snapshot_json=?, state_json=? WHERE battle_id=?",
                    (json.dumps(snapshot, sort_keys=True), json.dumps({"round_no": 0, "member_hp": {snapshot["members"][0]["player_id"]: 100000}, "enemy_hp": 500, "target_index": 0, "phase": "temptation"}, sort_keys=True), battle_id),
                )
                connection.execute("UPDATE final_battle_sessions SET status='running' WHERE battle_id=?", (battle_id,))

            ended = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "remain-choice"), f"选择终局战 留界 {battle_id}")
            assert ended.code == "FINAL_BATTLE_SETTLED"
            assert ended.data["outcome"] == "remained"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT endgame_status, ending_key, inventory_json, tribulation_debt FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert player[0:2] == ("remained_in_world", "remain_in_world")
                assert "item.ascension_certificate" not in json.loads(player[2])
                assert player[3] == 0
                ending = connection.execute(
                    "SELECT ending_key FROM endgame_endings WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                ).fetchone()
                assert ending == ("remain_in_world",)
                assert json.loads(player[2])["item.title.ascended"] == 1
            await runtime.close()

    asyncio.run(run())


def test_final_battle_failure_refunds_certificate_adds_debt_and_applies_cooldown() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "final-failure"
            await _create_player(runtime, adapter, user, leader=True)
            created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "final-fail-create"), "创建终局战")
            battle_id = created.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM final_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0])
                snapshot["enemy"]["max_hp"] = 5_000_000
                snapshot["enemy"]["attack"] = 100_000
                connection.execute(
                    "UPDATE final_battle_sessions SET snapshot_json=? WHERE battle_id=?",
                    (json.dumps(snapshot, sort_keys=True), battle_id),
                )

            failed = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "final-fail-start"), f"开始终局战 {battle_id}")
            assert failed.code == "FINAL_BATTLE_SETTLED"
            assert failed.data["outcome"] in {"lost", "expired"}
            assert failed.data["debt_delta"] == 25
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT inventory_json, tribulation_debt FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()
                assert json.loads(row[0]) == {"item.ascension_certificate": 1}
                assert row[1] == 25
            cooldown = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "final-fail-retry"), "创建终局战")
            assert cooldown.code == "FINAL_BATTLE_COOLDOWN"
            await runtime.close()

    asyncio.run(run())


def test_final_battle_lobby_timeout_releases_escrow_without_new_lobby() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "final-timeout"
            await _create_player(runtime, adapter, user, leader=True)
            created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "timeout-create"), "创建终局战")
            battle_id = created.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE final_battle_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE battle_id=?", (battle_id,))
            expired = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "timeout-access"), f"开始终局战 {battle_id}")
            assert expired.code == "FINAL_BATTLE_NOT_READY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()
                assert json.loads(player[0]) == {"item.ascension_certificate": 1}
                assert connection.execute(
                    "SELECT status FROM final_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0] == "expired"
                assert connection.execute(
                    "SELECT COUNT(*) FROM final_battle_members WHERE battle_id=? AND asset_lock_status='locked'", (battle_id,)
                ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_cancelled_final_battle_cannot_be_resolved_as_a_second_failure() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "final-cancel"
            await _create_player(runtime, adapter, user, leader=True)
            created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "cancel-create"), "创建终局战")
            battle_id = created.data["battle_id"]
            cancelled = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "cancel-battle"), f"取消终局战 {battle_id}")
            assert cancelled.code == "FINAL_BATTLE_CANCELLED"
            repeated = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "cancelled-start"), f"开始终局战 {battle_id}")
            assert repeated.code == "FINAL_BATTLE_NOT_READY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT inventory_json, tribulation_debt FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert json.loads(player[0]) == {"item.ascension_certificate": 1}
                assert player[1] == 0
            await runtime.close()

    asyncio.run(run())
