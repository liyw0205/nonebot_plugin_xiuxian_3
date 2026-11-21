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
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _create_cultivator(
    runtime, adapter: str, user: str, *, path: str = "体修",
    skills: tuple[str, ...] = ("基础攻击", "重击"),
) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        f"选择道途 {path}",
    )
    for index, command in enumerate(commands):
        result = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}-setup-{index}"), command
        )
        assert result.ok, (command, result.code, result.message)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET skill_insights=20, spirit_stones=10000, max_hp=999, initiative=99 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
    for index, skill in enumerate(skills):
        result = await runtime.adapters.dispatch(
            adapter, _context(adapter, user, f"{user}-train-{index}"), f"参悟神通 {skill}"
        )
        assert result.code == "SKILL_TRAINED", (skill, result.code, result.message)


def test_shared_tactic_commands_freeze_in_exploration_battle_and_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "tactic-qq"), ("onebot.v11", "tactic-onebot")):
                await _create_cultivator(runtime, adapter, user)
                profile = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-preview"), "战术预览"
                )
                assert profile.code == "COMBAT_TACTICS_PREVIEW"
                assert profile.data["preferred_skill_key"] is None
                assert {item["skill_key"] for item in profile.data["candidates"]} >= {
                    "skill.basic_attack", "skill.body.heavy_strike"
                }
                concurrent_sets = await asyncio.gather(*(
                    runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{user}-set-{index}", f"{user}-tactic-set"),
                        "设置战术 基础攻击",
                    )
                    for index in range(2)
                ))
                assert all(result.code == "COMBAT_TACTIC_SET" for result in concurrent_sets)
                assert sum(bool(result.data["idempotent_replay"]) for result in concurrent_sets) == 1
                configured = concurrent_sets[0]
                assert configured.data["preferred_skill_key"] == "skill.basic_attack"
                conflict = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-set-conflict", f"{user}-tactic-set"),
                    "设置战术 重击",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                preview = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-preview-configured"), "战术预览"
                )
                assert preview.data["selected_skill_key"] == "skill.basic_attack"
                reset = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-reset", f"{user}-tactic-reset"),
                    "设置战术 自动",
                )
                assert reset.code == "COMBAT_TACTIC_SET"
                assert reset.data["preferred_skill_key"] is None
                automatic = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"{user}-preview-reset"), "战术预览"
                )
                assert automatic.data["preferred_skill_key"] is None
                assert automatic.data["selected_skill_key"] == "skill.body.heavy_strike"
                configured_again = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-set-again", f"{user}-tactic-set-again"),
                    "设置战术 基础攻击",
                )
                assert configured_again.code == "COMBAT_TACTIC_SET"

            user = "tactic-qq"
            started = await runtime.repository.start_quest_battle(
                platform="qq.official", platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="tactic-battle-start",
            )
            busy = await runtime.adapters.dispatch(
                "qq.official",
                _context("qq.official", user, "tactic-battle-busy", "tactic-battle-busy"),
                "设置战术 自动",
            )
            assert busy.code == "TACTIC_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle_snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?", (started.battle_id,)
                ).fetchone()[0])
                assert battle_snapshot["player"]["preferred_skill_key"] == "skill.basic_attack"
                # A later preference edit must not replace the battle's frozen choice.
                connection.execute(
                    "UPDATE player_combat_tactics SET preferred_skill_key='skill.body.heavy_strike' "
                    "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    ("qq.official", user),
                )
            terminal = None
            for round_no in range(started.round_no + 1, 21):
                terminal = await runtime.repository.run_battle_turn(
                    battle_id=started.battle_id, expected_round=round_no
                )
                if terminal.status not in {"created", "running"}:
                    break
            assert terminal is not None and terminal.status not in {"created", "running"}
            await runtime.repository.resolve_battle(battle_id=started.battle_id)

            for index, tampered_preference in enumerate((None, "skill.tribulation.thunder")):
                historical = await runtime.repository.start_quest_battle(
                    platform="qq.official", platform_user_id=user,
                    enemy_key="enemy.wood_rat", battle_type="pve.encounter",
                    operation_id=f"tactic-historical-{index}",
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stored = json.loads(connection.execute(
                        "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                        (historical.battle_id,),
                    ).fetchone()[0])
                    if tampered_preference is None:
                        stored["player"].pop("preferred_skill_key", None)
                    else:
                        stored["player"]["preferred_skill_key"] = tampered_preference
                    connection.execute(
                        "UPDATE battle_sessions SET snapshot_json=? WHERE battle_id=?",
                        (json.dumps(stored, sort_keys=True), historical.battle_id),
                    )
                result = None
                for round_no in range(1, 21):
                    result = await runtime.repository.run_battle_turn(
                        battle_id=historical.battle_id, expected_round=round_no
                    )
                    if result.status not in {"created", "running"}:
                        break
                assert result is not None and result.status not in {"created", "running"}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    action = connection.execute(
                        "SELECT skill_key FROM battle_actions WHERE battle_id=? AND actor_key='player' "
                        "ORDER BY sequence_no LIMIT 1",
                        (historical.battle_id,),
                    ).fetchone()
                assert action is not None and action[0] == "skill.body.heavy_strike"
                await runtime.repository.resolve_battle(battle_id=historical.battle_id)
            await runtime.close()

            recovered = create_runtime(data_dir=data_dir)
            replay = await recovered.repository.replay_battle(
                platform="qq.official", platform_user_id=user, battle_id=started.battle_id
            )
            assert replay.snapshot["player"]["preferred_skill_key"] == "skill.basic_attack"
            first_action = next(action for action in replay.actions if action["actor_key"] == "player")
            assert first_action["skill_key"] == "skill.basic_attack"
            await recovered.close()

    asyncio.run(run())


def test_tactic_configuration_is_free_and_requires_write_permission() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create_cultivator(runtime, "onebot.v11", "tactic-permission")
            denied_context = CommandContext(
                adapter="onebot.v11", user_id="tactic-permission", can_write_assets=False,
                operation_id="tactic-read-only",
            )
            denied = await runtime.dispatch(denied_context, "设置战术 基础攻击")
            assert not denied.ok
            assert denied.code == "INVALID_CONTEXT"
            invalid = await runtime.dispatch(
                _context("onebot.v11", "tactic-permission", "unknown"), "设置战术 雷劫"
            )
            assert invalid.code == "TACTIC_SKILL_UNAVAILABLE"
            missing = await runtime.dispatch(
                _context("onebot.v11", "tactic-absent", "missing"), "设置战术 自动"
            )
            assert missing.code == "PLAYER_NOT_FOUND"
            unlearned = await runtime.dispatch(
                _context("onebot.v11", "tactic-permission", "wrong-path"), "设置战术 水箭"
            )
            assert unlearned.code == "TACTIC_SKILL_UNAVAILABLE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET path_key='spell' "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                )
            wrong_path = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "tactic-permission", "wrong-path-mastered"),
                "设置战术 重击",
            )
            assert wrong_path.code == "TACTIC_SKILL_UNAVAILABLE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET path_key='body' "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                )
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=1 "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                )
            realm_skill = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "tactic-permission", "train-realm-skill"),
                "参悟神通 崩山掌",
            )
            assert realm_skill.code == "SKILL_TRAINED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=2 "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                )
            unmet_realm = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "tactic-permission", "unmet-realm"),
                "设置战术 崩山掌",
            )
            assert unmet_realm.code == "TACTIC_SKILL_UNAVAILABLE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=1 "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                )
                before = connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                ).fetchone()
                events_before = connection.execute(
                    "SELECT COUNT(*) FROM skill_resource_events WHERE player_id="
                    "(SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id='tactic-permission')"
                ).fetchone()[0]
            bad_arity = await runtime.dispatch(
                _context("onebot.v11", "tactic-permission", "arity"), "设置战术 基础攻击 重击"
            )
            assert bad_arity.code == "INVALID_TACTIC_COMMAND"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_tactic_receipt BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name='combat.tactic.set' BEGIN "
                    "SELECT RAISE(ABORT, 'simulated receipt failure'); END"
                )
            failed = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "tactic-permission", "rollback", "tactic-rollback"),
                "设置战术 基础攻击",
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM player_combat_tactics WHERE player_id="
                    "(SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id='tactic-permission')"
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='tactic-rollback'"
                ).fetchone()[0] == 0
                connection.execute("DROP TRIGGER reject_tactic_receipt")
            retried = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "tactic-permission", "rollback-retry", "tactic-rollback"),
                "设置战术 基础攻击",
            )
            assert retried.code == "COMBAT_TACTIC_SET"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players "
                    "WHERE platform='onebot.v11' AND platform_user_id='tactic-permission'"
                ).fetchone()
                events = connection.execute(
                    "SELECT COUNT(*) FROM skill_resource_events WHERE player_id="
                    "(SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id='tactic-permission')"
                ).fetchone()[0]
            assert after == before
            assert events == events_before
            await runtime.close()

    asyncio.run(run())


def test_tactics_require_active_cultivator_and_active_player_status() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            novice = await runtime.adapters.dispatch(
                "web", _context("web", "tactic-novice", "tactic-novice-create"), "开始修仙"
            )
            assert novice.code == "PLAYER_CREATED"
            rejected = await runtime.adapters.dispatch(
                "web",
                _context("web", "tactic-novice", "tactic-novice-set", "tactic-novice-set"),
                "设置战术 自动",
            )
            assert rejected.code == "TACTIC_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', path_key='body', status='suspended' "
                    "WHERE platform='web' AND platform_user_id='tactic-novice'"
                )
            suspended = await runtime.adapters.dispatch(
                "web",
                _context("web", "tactic-novice", "tactic-suspended-set", "tactic-suspended-set"),
                "设置战术 自动",
            )
            assert suspended.code == "PLAYER_SUSPENDED"
            await runtime.close()

    asyncio.run(run())


def test_spell_tactic_falls_back_when_current_mana_is_insufficient() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "tactic-mana-fallback"
            await _create_cultivator(
                runtime, adapter, user, path="法修", skills=("基础攻击", "水箭")
            )
            selected = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "select-water-bolt", "select-water-bolt"),
                "设置战术 水箭",
            )
            assert selected.code == "COMBAT_TACTIC_SET"
            started = await runtime.repository.start_quest_battle(
                platform=adapter, platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="tactic-mana-battle",
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()[0])
                assert snapshot["player"]["preferred_skill_key"] == "skill.spell.water_bolt"
                state = json.loads(connection.execute(
                    "SELECT state_json FROM battle_sessions WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()[0])
                state["player_mana"] = 0
                connection.execute(
                    "UPDATE battle_sessions SET state_json=? WHERE battle_id=?",
                    (json.dumps(state, sort_keys=True), started.battle_id),
                )
            await runtime.repository.run_battle_turn(
                battle_id=started.battle_id, expected_round=1
            )
            replay = await runtime.repository.replay_battle(
                platform=adapter, platform_user_id=user, battle_id=started.battle_id
            )
            player_action = next(action for action in replay.actions if action["actor_key"] == "player")
            assert player_action["skill_key"] == "skill.basic_attack"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = json.loads(connection.execute(
                    "SELECT state_json FROM battle_sessions WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()[0])
            assert state["player_mana"] >= 0
            await runtime.close()

    asyncio.run(run())


def test_exploration_freezes_preference_before_linked_encounter() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "tactic-exploration-freeze"
            await _create_cultivator(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=2, "
                    "location_key='xuantian.outskirts', stamina=100, max_hp=999, initiative=99 "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            configured = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "exploration-configure", "exploration-configure"),
                "设置战术 重击",
            )
            assert configured.code == "COMBAT_TACTIC_SET"
            operation = next(
                f"tactic-exploration-{index}"
                for index in range(1000)
                if battle_roll_bp(f"tactic-exploration-{index}:battle") < 1000
            )
            started = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation, operation), "开始探索 短历练"
            )
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen = json.loads(connection.execute(
                    "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                    (exploration_id,),
                ).fetchone()[0])
                assert frozen["preferred_skill_key"] == "skill.body.heavy_strike"
                connection.execute(
                    "UPDATE player_combat_tactics SET preferred_skill_key='skill.basic_attack' "
                    "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                )
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
                )
            denied = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "exploration-edit-denied", "exploration-edit-denied"),
                "设置战术 基础攻击",
            )
            assert denied.code == "TACTIC_BUSY"
            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "exploration-settle"), "结算探索"
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == "won"
            replay = await runtime.repository.replay_battle(
                platform=adapter, platform_user_id=user,
                battle_id=str(settled.data["battle_id"]),
            )
            assert replay.snapshot["player"]["preferred_skill_key"] == "skill.body.heavy_strike"
            first_action = next(action for action in replay.actions if action["actor_key"] == "player")
            assert first_action["skill_key"] == "skill.body.heavy_strike"
            await runtime.close()

    asyncio.run(run())


def test_other_battle_capable_exploration_freezes_preference() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "tactic-ironwood-gather"
            await _create_cultivator(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=1, "
                    "location_key='xuantian.ironwood_grove', stamina=100 "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            configured = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "ironwood-tactic", "ironwood-tactic"),
                "设置战术 重击",
            )
            assert configured.code == "COMBAT_TACTIC_SET"

            started = await runtime.repository.start_exploration(
                platform=adapter, platform_user_id=user,
                mode_key="explore.gather_ironwood", operation_id="ironwood-gather-start",
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(connection.execute(
                    "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                    (started.exploration_id,),
                ).fetchone()[0])
            assert snapshot["mode_key"] == "explore.gather_ironwood"
            assert snapshot["preferred_skill_key"] == "skill.body.heavy_strike"
            await runtime.close()

    asyncio.run(run())


def test_started_tactic_survives_content_closure_and_new_selection_is_rejected() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "tactic-content-closure"
            await _create_cultivator(runtime, adapter, user)
            configured = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "content-configure", "content-configure"),
                "设置战术 重击",
            )
            assert configured.code == "COMBAT_TACTIC_SET"
            started = await runtime.repository.start_quest_battle(
                platform=adapter, platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="tactic-content-battle",
            )
            await runtime.close()

            skill_path = data_dir / "技能" / "技能.json"
            document = json.loads(skill_path.read_text(encoding="utf-8"))
            heavy_strike = next(
                item for item in document["records"] if item["key"] == "skill.body.heavy_strike"
            )
            heavy_strike["status"] = "open"
            heavy_strike["effect"]["value"] = 19000
            skill_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

            recovered = create_runtime(data_dir=data_dir)
            terminal = None
            for round_no in range(1, 21):
                terminal = await recovered.repository.run_battle_turn(
                    battle_id=started.battle_id, expected_round=round_no
                )
                if terminal.status not in {"created", "running"}:
                    break
            assert terminal is not None and terminal.status not in {"created", "running"}
            replay = await recovered.repository.replay_battle(
                platform=adapter, platform_user_id=user, battle_id=started.battle_id
            )
            assert replay.snapshot["player"]["preferred_skill_key"] == "skill.body.heavy_strike"
            first_action = next(action for action in replay.actions if action["actor_key"] == "player")
            assert first_action["skill_key"] == "skill.body.heavy_strike"
            await recovered.repository.resolve_battle(battle_id=started.battle_id)
            profile = await recovered.adapters.dispatch(
                adapter, _context(adapter, user, "content-closed-preview"), "战术预览"
            )
            assert profile.data["preference_available"] is False
            assert profile.data["selected_skill_key"] == "skill.body.heavy_strike"
            refused = await recovered.adapters.dispatch(
                adapter,
                _context(adapter, user, "content-closed-set", "content-closed-set"),
                "设置战术 重击",
            )
            assert refused.code == "TACTIC_SKILL_UNAVAILABLE"
            original_operation = await recovered.adapters.dispatch(
                adapter,
                _context(adapter, user, "content-configure-replay", "content-configure"),
                "设置战术 重击",
            )
            assert original_operation.code == "COMBAT_TACTIC_SET"
            assert original_operation.data["preferred_skill_key"] == "skill.body.heavy_strike"
            assert original_operation.data["idempotent_replay"] is True
            await recovered.close()

    asyncio.run(run())


def test_combat_tactic_schema_upgrade_preserves_existing_player_rows() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            created = await runtime.dispatch(
                _context("web", "tactic-schema-player", "create"), "开始修仙"
            )
            assert created.code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', path_key='body', realm_key='qi_sensing', "
                    "realm_layer=2, location_key='xuantian.outskirts', max_hp=999, qualification_json=? "
                    "WHERE platform='web' AND platform_user_id='tactic-schema-player'",
                    (json.dumps({"body": 15, "spirit": 10, "insight": 10, "root": 10, "agility": 8, "fortune": 7}),),
                )
            battle = await runtime.repository.start_quest_battle(
                platform="web", platform_user_id="tactic-schema-player",
                enemy_key="enemy.wood_rat", battle_type="pve.encounter",
                operation_id="tactic-schema-history",
            )
            await runtime.repository.run_battle_turn(
                battle_id=battle.battle_id, expected_round=1
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_count = connection.execute("SELECT COUNT(*) FROM players").fetchone()[0]
                battle_count = connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0]
                action_count = connection.execute("SELECT COUNT(*) FROM battle_actions").fetchone()[0]
                connection.execute("DROP TABLE player_combat_tactics")
            await runtime.close()

            upgraded = create_runtime(data_dir=data_dir)
            await upgraded.repository.initialize()
            with sqlite3.connect(upgraded.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM players").fetchone()[0] == player_count
                assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == battle_count
                assert connection.execute("SELECT COUNT(*) FROM battle_actions").fetchone()[0] == action_count
                columns = {row[1] for row in connection.execute("PRAGMA table_info(player_combat_tactics)")}
                assert {"player_id", "preferred_skill_key", "updated_at"} <= columns
            await upgraded.repository.initialize()
            with sqlite3.connect(upgraded.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM players").fetchone()[0] == player_count
                assert connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_combat_tactics'"
                ).fetchone() is not None
            await upgraded.close()

    asyncio.run(run())
