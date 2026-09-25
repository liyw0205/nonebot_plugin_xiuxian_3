from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        ("create", "开始修仙"),
        ("seek", "寻仙问道"),
        ("read", "完成引导 阅读"),
        ("travel", "前往近郊"),
        ("gather", "完成引导 采集"),
        ("service", "完成引导 炼丹"),
        ("path", "选择道途 体修"),
        ("return", "返回新手城"),
    )
    for request, text in commands:
        result = await runtime.dispatch(_context(user_id, request), text)
        assert result.ok, (text, result.code)


def _insert_weapon(runtime, user_id: str, durability_bp: int = 100) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform = 'web' AND platform_user_id = ?", (user_id,)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO equipment_instances(
                instance_id, player_id, item_key, label, slot, status, durability_bp,
                temper_level, max_temper_level, affixes_json, refinement_failure_streak,
                created_at, updated_at
            ) VALUES (?, ?, 'item.weapon.wood_sword', '木纹剑', 'weapon', 'active', ?, 0, 3, '{}', 0, ?, ?)
            """,
            (f"weapon-{user_id}", player_id, durability_bp, now, now),
        )


def test_training_battle_is_automatic_replayable_and_reward_is_unique() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-win"
            await _enter_cultivator(runtime, user)
            _insert_weapon(runtime, user)

            before = await runtime.dispatch(_context(user, "before"), "我的状态")
            settled = await runtime.dispatch(
                _context(user, "battle", operation_id="combat-win-start"), "开始训练战"
            )
            assert settled.code == "BATTLE_SETTLED"
            assert settled.data["outcome"] == "won"
            assert settled.data["reward_status"] == "pending"
            assert settled.data["reward"] == {"cultivation": 20, "spirit_stones": 5}
            after_settlement = await runtime.dispatch(_context(user, "after-settle"), "我的状态")
            assert after_settlement.data["cultivation"] == before.data["cultivation"]
            assert after_settlement.data["spirit_stones"] == before.data["spirit_stones"]

            replay = await runtime.dispatch(_context(user, "replay"), "战斗回放")
            assert replay.code == "BATTLE_REPLAY"
            assert replay.data["battle_id"] == settled.data["battle_id"]
            assert replay.data["snapshot"]["enemy"]["key"] == "enemy.training_dummy"
            assert replay.data["snapshot"]["random_pool"] == "battle.enemy.training_dummy.v0.1"
            assert replay.data["actions"]
            assert all(action["skill_key"] in {"skill.basic_attack", "enemy_skill.dummy_tap"} for action in replay.data["actions"])
            assert all("operation_id" in action for action in replay.data["actions"])

            with sqlite3.connect(runtime.settings.database_path) as connection:
                durability = connection.execute(
                    "SELECT durability_bp FROM equipment_instances WHERE instance_id = ?", (f"weapon-{user}",)
                ).fetchone()[0]
            assert durability == 50

            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="combat-win-claim"), "领取战斗奖励"
            )
            assert claimed.code == "BATTLE_REWARD_CLAIMED"
            replayed_claim = await runtime.dispatch(
                _context(user, "claim-replay", operation_id="combat-win-claim"), "领取战斗奖励"
            )
            assert replayed_claim.code == "BATTLE_REWARD_CLAIMED"
            assert replayed_claim.data["idempotent_replay"] is True
            final = await runtime.dispatch(_context(user, "final"), "我的状态")
            assert final.data["cultivation"] == before.data["cultivation"] + 20
            assert final.data["spirit_stones"] == before.data["spirit_stones"] + 5
            duplicate = await runtime.dispatch(
                _context(user, "claim-duplicate", operation_id="combat-win-claim-duplicate"), "领取战斗奖励"
            )
            assert duplicate.code == "BATTLE_REWARD_ALREADY_CLAIMED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET initiative = 999, qualification_json = ? WHERE platform_user_id = ?",
                    (json.dumps({"body": 15, "spirit": 5, "insight": 5, "root": 15, "agility": 15, "fortune": 5}), user),
                )
            replay_after_player_change = await runtime.dispatch(
                _context(user, "replay-after-change"), f"战斗回放 {settled.data['battle_id']}"
            )
            assert replay_after_player_change.data["snapshot"] == replay.data["snapshot"]
            assert replay_after_player_change.data["actions"] == replay.data["actions"]
            await runtime.close()

    asyncio.run(run())


def test_training_battle_rejects_client_action_fields_and_missing_prerequisites() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-requirement"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            missing = await runtime.dispatch(_context(user, "missing"), "开始训练战")
            assert missing.code == "BATTLE_REQUIREMENT_MISSING"
            await _enter_cultivator(runtime, "combat-command")
            forged = await runtime.dispatch(
                _context("combat-command", "forged"), "开始训练战 skill.basic_attack enemy.training_dummy 99999"
            )
            assert forged.code == "INVALID_BATTLE_COMMAND"
            assert (await runtime.dispatch(_context("combat-command", "check"), "战斗回放")).code == "BATTLE_NOT_FOUND"
            await runtime.close()

    asyncio.run(run())


def test_mastered_skill_is_frozen_and_used_by_automatic_battle() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-skilled"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET skill_insights=1, spirit_stones=20 WHERE platform='web' AND platform_user_id=?",
                    (user,),
                )
            trained = await runtime.dispatch(_context(user, "skill-train"), "参悟神通 重击")
            assert trained.code == "SKILL_TRAINED"
            settled = await runtime.dispatch(
                _context(user, "skill-battle", operation_id="combat-skilled-start"), "开始训练战"
            )
            assert settled.code == "BATTLE_SETTLED"
            replay = await runtime.dispatch(_context(user, "skill-replay"), "战斗回放")
            skills = replay.data["snapshot"]["player"]["skills"]
            assert skills[0]["skill_key"] == "skill.body.heavy_strike"
            assert any(action["skill_key"] == "skill.body.heavy_strike" for action in replay.data["actions"])
            await runtime.close()

    asyncio.run(run())


def test_training_battle_recovers_from_created_session_after_runtime_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            user = "combat-recovery"
            runtime = create_runtime(data_dir=data_dir)
            await _enter_cultivator(runtime, user)
            started = await runtime.repository.start_training_battle(
                platform="web", platform_user_id=user, operation_id="combat-recovery-start"
            )
            assert started.status == "created"
            await runtime.close()

            recovered_runtime = create_runtime(data_dir=data_dir)
            settled = await recovered_runtime.dispatch(
                _context(user, "retry", operation_id="combat-recovery-start"), "开始训练战"
            )
            assert settled.code == "BATTLE_SETTLED"
            assert settled.data["outcome"] == "won"
            assert settled.data["idempotent_replay"] is True
            replay = await recovered_runtime.dispatch(_context(user, "replay"), "战斗回放")
            assert replay.data["actions"]
            await recovered_runtime.close()

    asyncio.run(run())


def test_three_server_timeouts_lose_without_durability_loss() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-timeout"
            await _enter_cultivator(runtime, user)
            _insert_weapon(runtime, user)
            started = await runtime.repository.start_training_battle(
                platform="web", platform_user_id=user, operation_id="combat-timeout-start"
            )
            for expected_round in range(1, 4):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE battle_sessions SET turn_deadline = ? WHERE battle_id = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.battle_id),
                    )
                turn = await runtime.repository.run_battle_turn(
                    battle_id=started.battle_id, expected_round=expected_round
                )
            assert turn.status == "lost"
            resolution = await runtime.repository.resolve_battle(battle_id=started.battle_id)
            assert resolution.outcome == "lost"
            assert resolution.reward == {}
            replay = await runtime.repository.replay_battle(
                platform="web", platform_user_id=user, battle_id=started.battle_id
            )
            assert sum(action["skill_key"] == "skill.defend" for action in replay.actions) == 3
            with sqlite3.connect(runtime.settings.database_path) as connection:
                durability = connection.execute(
                    "SELECT durability_bp FROM equipment_instances WHERE instance_id = ?", (f"weapon-{user}",)
                ).fetchone()[0]
                cooldown = connection.execute(
                    "SELECT battle_defeat_until FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
            assert durability == 100
            assert cooldown is not None
            await runtime.close()

    asyncio.run(run())


def test_combat_schema_migrates_legacy_player_table() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            runtime.settings.data_dir.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE players (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform TEXT NOT NULL,
                        platform_user_id TEXT NOT NULL,
                        scene_id TEXT NOT NULL DEFAULT '',
                        nickname TEXT NOT NULL DEFAULT '',
                        stage TEXT NOT NULL,
                        qualification_json TEXT NOT NULL DEFAULT '{}',
                        spirit_stones INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE (platform, platform_user_id)
                    )
                    """
                )
            await runtime.initialize()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(players)")}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert "battle_defeat_until" in columns
            assert {"battle_sessions", "battle_actions", "battle_reward_claims"} <= tables
            await runtime.close()

    asyncio.run(run())
