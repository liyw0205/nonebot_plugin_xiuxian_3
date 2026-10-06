from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.skill_effects import (
    apply_player_skill_style,
    mitigate_enemy_attack,
    mitigate_player_damage,
    prepare_skill_action,
    reflected_enemy_damage,
)
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import build_stat_preview


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


def _insert_armor(runtime, user_id: str) -> None:
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
            ) VALUES (?, ?, 'item.armor.cotton_robe', '棉袍', 'armor', 'active', 10000, 0, 3, '{}', 0, ?, ?)
            """,
            (f"armor-{user_id}", player_id, now, now),
        )


async def _run_real_pve(runtime, user_id: str, operation_id: str, *, enemy_key: str = "enemy.wood_rat"):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET location_key='xuantian.outskirts' WHERE platform='web' AND platform_user_id=?",
            (user_id,),
        )
    started = await runtime.repository.start_quest_battle(
        platform="web",
        platform_user_id=user_id,
        enemy_key=enemy_key,
        battle_type="pve.encounter",
        operation_id=operation_id,
    )
    turn = None
    for expected_round in range(started.round_no + 1, 21):
        turn = await runtime.repository.run_battle_turn(
            battle_id=started.battle_id, expected_round=expected_round
        )
        if turn.status not in {"created", "running"}:
            break
    assert turn is not None and turn.status not in {"created", "running"}
    resolved = await runtime.repository.resolve_battle(battle_id=started.battle_id)
    replay = await runtime.repository.replay_battle(
        platform="web", platform_user_id=user_id, battle_id=started.battle_id
    )
    return started, resolved, replay


def test_real_pve_settles_with_replay_durability_and_codex() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-win"
            await _enter_cultivator(runtime, user)
            _insert_weapon(runtime, user)
            before = await runtime.dispatch(_context(user, "before"), "我的状态")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                codex_before = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE p.platform='web' AND p.platform_user_id=?",
                    (user,),
                ).fetchone()[0]
            started, resolved, replay = await _run_real_pve(runtime, user, "combat-win-start")
            assert resolved.outcome == "won"
            assert resolved.reward_status == "none"
            assert resolved.reward == {}
            assert replay.enemy_key == "enemy.wood_rat"
            assert replay.actions
            assert all("operation_id" in action for action in replay.actions)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                durability = connection.execute(
                    "SELECT durability_bp FROM equipment_instances WHERE instance_id = ?", (f"weapon-{user}",)
                ).fetchone()[0]
                codex_after = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE p.platform='web' AND p.platform_user_id=?",
                    (user,),
                ).fetchone()[0]
            assert durability == 50
            assert codex_after == codex_before + 1

            claimed = await runtime.dispatch(_context(user, "claim", operation_id="combat-win-claim"), "领取战斗奖励")
            assert claimed.code == "BATTLE_REWARD_NOT_AVAILABLE"
            final = await runtime.dispatch(_context(user, "final"), "我的状态")
            assert final.data["cultivation"] == before.data["cultivation"]
            assert final.data["spirit_stones"] == before.data["spirit_stones"]

            assert started.battle_id
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
    async def run(data_dir: Path) -> None:
        skill_path = data_dir / "技能" / "技能.json"
        skill_data = json.loads(skill_path.read_text(encoding="utf-8"))
        heavy_strike = next(row for row in skill_data["records"] if row["key"] == "skill.body.heavy_strike")
        heavy_strike["effect"]["value"] = 22_000
        skill_path.write_text(json.dumps(skill_data, ensure_ascii=False, indent=2), encoding="utf-8")

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
        assert trained.data["effective_effect"]["value"] == 22_300
        _, settled, replay = await _run_real_pve(runtime, user, "combat-skilled-start")
        assert settled.outcome == "won"
        battle_snapshot = replay.snapshot
        skills = battle_snapshot["player"]["skills"]
        assert skills[0]["skill_key"] == "skill.body.heavy_strike"
        assert skills[0]["effect"]["value"] == 22_300
        action = next(
            action
            for action in replay.actions
            if action["actor_key"] == "player" and action["skill_key"] == "skill.body.heavy_strike"
        )
        assert action["hit_roll_bp"] < action["hit_bp"]
        assert action["damage"] == min(
            battle_snapshot["enemy"]["max_hp"],
            battle_snapshot["player"]["stats"]["attack"] * 22_300 // 10_000,
        )
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_sustained_skill_style_is_frozen_and_consumed_by_automatic_battle() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-sustained-skill"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='foundation', realm_layer=1, skill_insights=20, "
                    "spirit_stones=10000, initiative=100, inventory_json=? "
                    "WHERE platform='web' AND platform_user_id=?",
                    (json.dumps({"item.manual.skill_legacy": 1}), user),
                )
            trained = await runtime.dispatch(
                _context(user, "train-sustained"),
                "参悟神通 skill.body.qi_gathering.variant",
            )
            assert trained.code == "SKILL_TRAINED"
            _, settled, replay_record = await _run_real_pve(runtime, user, "sustained-run-0")
            assert settled.outcome == "won"
            replay = replay_record
            skill = next(
                item for item in replay.snapshot["player"]["skills"]
                if item["skill_key"] == "skill.body.qi_gathering.variant"
            )
            assert skill["combat_style"]["key"] == "sustained"
            player_actions = [
                action for action in replay.actions
                if action["actor_key"] == "player"
                and action["skill_key"] == "skill.body.qi_gathering.variant"
            ]
            assert player_actions[0]["state"]["skill_statuses"]["sustained"]["damage"] > 0
            assert len(player_actions) > 1
            assert player_actions[1]["damage"] > 0
            assert any(
                action["state"].get("skill_statuses", {}).get("sustained", {}).get("start_round")
                < action["state"].get("skill_statuses", {}).get("sustained", {}).get("end_round")
                for action in player_actions
            )
            await runtime.close()

    asyncio.run(run())


def test_owned_manual_combat_passives_are_frozen_and_reflect_damage() -> None:
    async def run(data_dir: Path) -> None:
        manuals_path = data_dir / "道具" / "功法.json"
        manuals = json.loads(manuals_path.read_text(encoding="utf-8"))
        manual = next(row for row in manuals["records"] if row["key"] == "item.manual.basic_qi")
        manual["effects"] = [
            effect
            for effect in manual["effects"]
            if effect.get("type") not in {"combat_stat_bonus_bp", "damage_reflection_bp"}
        ]
        manual["effects"].extend(
            (
                {"type": "combat_stat_bonus_bp", "stat": "attack", "value": 1000},
                {"type": "damage_reflection_bp", "value": 5000},
            )
        )
        manuals_path.write_text(json.dumps(manuals, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        user = "combat-manual-passives"
        await _enter_cultivator(runtime, user)
        _, settled, replay = await _run_real_pve(runtime, user, "manual-reflect-battle")
        assert settled.outcome == "won"
        effects = replay.snapshot["player"]["manual_effects"]
        assert effects["combat_stat_bonus_bp"]["attack"] == 1000
        assert effects["damage_reflection_bp"] == 5000
        assert replay.snapshot["player"]["stats"]["damage_reflection_bp"] == 5000
        assert any(
            action["actor_key"] == "enemy"
            and action["state"].get("reflected_damage", 0) > 0
            for action in replay.actions
        )
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_equipment_flat_stats_are_loaded_from_content_and_frozen_in_battle() -> None:
    async def run(data_dir: Path) -> None:
        weapon_path = data_dir / "装备" / "法器.json"
        weapon_data = json.loads(weapon_path.read_text(encoding="utf-8"))
        wood_sword = next(row for row in weapon_data["records"] if row["key"] == "item.weapon.wood_sword")
        wood_sword["effects"][0]["value"] = 17
        wood_sword["effects"].append({"type": "flat_stat", "stat": "initiative", "value": 800})
        weapon_path.write_text(json.dumps(weapon_data, ensure_ascii=False, indent=2), encoding="utf-8")

        armor_path = data_dir / "装备" / "防具.json"
        armor_data = json.loads(armor_path.read_text(encoding="utf-8"))
        cotton_robe = next(row for row in armor_data["records"] if row["key"] == "item.armor.cotton_robe")
        cotton_robe["effects"][0]["value"] = 35
        cotton_robe["effects"].append({"type": "flat_stat", "stat": "agility", "value": 900})
        armor_path.write_text(json.dumps(armor_data, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        user = "combat-equipment-content"
        await _enter_cultivator(runtime, user)
        _insert_weapon(runtime, user, durability_bp=10_000)
        _insert_armor(runtime, user)
        with runtime.repository._connect() as connection:
            player = connection.execute(
                "SELECT * FROM players WHERE platform = 'web' AND platform_user_id = ?", (user,)
            ).fetchone()
            expected = runtime.repository._build_player_stat_snapshot(connection, player)

        _, settled, replay = await _run_real_pve(runtime, user, "equipment-content-battle")
        assert settled.outcome == "won"
        battle_snapshot = replay.snapshot
        stats = battle_snapshot["player"]["stats"]
        assert stats == expected["combat_stats"]
        assert stats["initiative"] >= 800
        assert stats["agility"] >= 900
        effects = {item["item_key"]: item["effects"] for item in battle_snapshot["player"]["equipment"]}
        assert effects["item.weapon.wood_sword"][0]["value"] == 17
        assert effects["item.armor.cotton_robe"][0]["value"] == 35
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_path_accessory_effects_are_frozen_and_change_combat_stats() -> None:
    async def run(data_dir: Path) -> None:
        runtime = create_runtime(data_dir=data_dir)
        user = "combat-accessory-snapshot"
        await _enter_cultivator(runtime, user)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform='web' AND platform_user_id=?", (user,)
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO equipment_instances(
                    instance_id, player_id, item_key, label, slot, status, durability_bp,
                    temper_level, max_temper_level, affixes_json, refinement_failure_streak,
                    created_at, updated_at
                ) VALUES (?, ?, 'item.accessory.body.stone_pulse_bracer', '石脉护腕', 'accessory', 'active', 10000, 0, 3, '{}', 0, ?, ?)
                """,
                (f"accessory-{user}", player_id, now, now),
            )

        _, settled, replay = await _run_real_pve(runtime, user, "accessory-snapshot-battle")
        assert settled.outcome == "won"
        player_snapshot = replay.snapshot["player"]
        accessory = next(
            item for item in player_snapshot["equipment"]
            if item["item_key"] == "item.accessory.body.stone_pulse_bracer"
        )
        assert accessory["effects"] == [
            {"type": "flat_stat", "stat": "physical_damage", "value": 3},
            {"type": "combat_stat_bp", "stat": "accuracy_bp", "value": 120},
        ]
        assert player_snapshot["stats"]["attack"] >= 13
        assert player_snapshot["stats"]["accuracy_bp"] == 120
        assert player_snapshot["stats"]["max_mana"] > 0
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_equipment_effects_cover_the_full_combat_stat_set() -> None:
    effects = [
        {"type": "flat_stat", "stat": "physical_damage", "value": 5},
        {"type": "flat_stat", "stat": "max_hp", "value": 20},
        {"type": "flat_stat", "stat": "max_mana", "value": 30},
        {"type": "flat_stat", "stat": "hp_regen", "value": 4},
        {"type": "flat_stat", "stat": "mana_regen", "value": 3},
        {"type": "flat_stat", "stat": "initiative", "value": 2},
        *[
            {"type": "combat_stat_bp", "stat": stat, "value": value}
            for stat, value in (
                ("damage_reduction_bp", 100),
                ("crit_chance_bp", 200),
                ("crit_damage_bp", 300),
                ("evasion_bp", 400),
                ("accuracy_bp", 500),
                ("anti_crit_bp", 600),
                ("damage_reflection_bp", 700),
                ("lifesteal_bp", 800),
                ("mana_leech_bp", 900),
                ("healing_reduction_bp", 1_000),
                ("recovery_reduction_bp", 1_100),
            )
        ],
    ]
    row = {"realm_key": "mortal", "realm_layer": 0,
           "qualification": dict.fromkeys(("body", "spirit", "insight", "root", "agility", "fortune"), 10)}
    base = build_stat_preview(row)["combat_stats"]
    stats = build_stat_preview(
        row,
        equipment=({"item_key": "item.accessory.test", "slot": "accessory", "durability_bp": 10_000,
                    "temper_level": 0, "affixes": {}, "effects": effects},),
    )["combat_stats"]
    assert stats["attack"] == base["attack"] + 5
    assert stats["max_hp"] == base["max_hp"] + 20
    assert stats["max_mana"] == base["max_mana"] + 30
    assert stats["initiative"] == base["initiative"] + 2
    assert stats["hp_regen"] == 4
    assert stats["mana_regen"] == 3
    assert {stat: stats[stat] for stat in (
        "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp",
        "accuracy_bp", "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp",
        "mana_leech_bp", "healing_reduction_bp", "recovery_reduction_bp",
    )} == {
        "damage_reduction_bp": 100,
        "crit_chance_bp": 200,
        "crit_damage_bp": 300,
        "evasion_bp": 400,
        "accuracy_bp": 500,
        "anti_crit_bp": 600,
        "damage_reflection_bp": 700,
        "lifesteal_bp": 800,
        "mana_leech_bp": 900,
        "healing_reduction_bp": 1_000,
        "recovery_reduction_bp": 1_100,
    }


def test_real_pve_recovers_from_created_session_after_runtime_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            user = "combat-recovery"
            runtime = create_runtime(data_dir=data_dir)
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.outskirts' WHERE platform='web' AND platform_user_id=?",
                    (user,),
                )
            started = await runtime.repository.start_quest_battle(
                platform="web", platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="combat-recovery-start"
            )
            assert started.status == "created"
            await runtime.close()

            recovered_runtime = create_runtime(data_dir=data_dir)
            replay_start = await recovered_runtime.repository.start_quest_battle(
                platform="web", platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="combat-recovery-start"
            )
            assert replay_start.already_completed is True
            for expected_round in range(1, 21):
                turn = await recovered_runtime.repository.run_battle_turn(
                    battle_id=started.battle_id, expected_round=expected_round
                )
                if turn.status not in {"created", "running"}:
                    break
            settled = await recovered_runtime.repository.resolve_battle(battle_id=started.battle_id)
            assert settled.outcome == "won"
            replay = await recovered_runtime.repository.replay_battle(
                platform="web", platform_user_id=user, battle_id=started.battle_id
            )
            assert replay.actions
            await recovered_runtime.close()

    asyncio.run(run())


def test_three_server_timeouts_lose_without_durability_loss() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "combat-timeout"
            await _enter_cultivator(runtime, user)
            _insert_weapon(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.outskirts' WHERE platform='web' AND platform_user_id=?",
                    (user,),
                )
            started = await runtime.repository.start_quest_battle(
                platform="web", platform_user_id=user, enemy_key="enemy.wood_rat",
                battle_type="pve.encounter", operation_id="combat-timeout-start"
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
            assert cooldown is None
            await runtime.close()

    asyncio.run(run())


def test_combat_schema_exposes_current_tables() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(players)")}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert "battle_defeat_until" in columns
            assert {"battle_sessions", "battle_actions", "battle_reward_claims"} <= tables
            await runtime.close()

    asyncio.run(run())


def test_configured_skill_styles_have_distinct_battle_effects() -> None:
    support = {
        "skill_key": "skill.test.support",
        "effect": {"type": "physical_damage_multiplier_bp", "value": 12_000},
        "combat_style": {"key": "support", "effect": {"damage_reduction_bp": 2_000, "duration_rounds": 1}},
    }
    state: dict[str, object] = {}
    apply_player_skill_style(
        support, state, round_no=1, player_attack=100, hit=True, enemy_acted=False
    )
    assert mitigate_player_damage(100, state, round_no=1) == 80
    assert mitigate_player_damage(100, state, round_no=2) == 100

    sustained = {
        "skill_key": "skill.test.sustained",
        "effect": {"type": "spell_damage_multiplier_bp", "value": 10_000},
        "combat_style": {"key": "sustained", "effect": {"damage_over_time_bp": 2_000, "duration_rounds": 2}},
    }
    state = {}
    assert apply_player_skill_style(
        sustained, state, round_no=1, player_attack=100, hit=True, enemy_acted=False
    ) == 0
    assert apply_player_skill_style(
        sustained, state, round_no=2, player_attack=100, hit=False, enemy_acted=False
    ) == 20
    assert apply_player_skill_style(
        sustained, state, round_no=3, player_attack=100, hit=False, enemy_acted=False
    ) == 20
    assert apply_player_skill_style(
        sustained, state, round_no=4, player_attack=100, hit=False, enemy_acted=False
    ) == 0

    negative = {
        "skill_key": "skill.test.negative",
        "effect": {"type": "spell_damage_multiplier_bp", "value": 10_000},
        "combat_style": {"key": "negative", "effect": {"enemy_attack_reduction_bp": 2_500, "duration_rounds": 1}},
    }
    state = {}
    apply_player_skill_style(
        negative, state, round_no=1, player_attack=100, hit=True, enemy_acted=False
    )
    assert mitigate_enemy_attack(100, state, round_no=1) == 75
    assert mitigate_enemy_attack(100, state, round_no=2) == 100

    charged = {
        "skill_key": "skill.test.charge",
        "effect": {"type": "physical_damage_multiplier_bp", "value": 15_000},
        "combat_style": {"key": "charge", "effect": {"charge_multiplier_bp": 18_000}},
    }
    state = {}
    assert prepare_skill_action(charged, state, 1) == (0, 0, True)
    assert prepare_skill_action(charged, state, 2) == (27_000, 0, False)

    burst = {
        "skill_key": "skill.test.burst",
        "effect": {"type": "physical_damage_multiplier_bp", "value": 15_000},
        "combat_style": {"key": "burst", "effect": {"hit_penalty_bp": 1_200}},
    }
    assert prepare_skill_action(burst, {}, 1) == (15_000, -1_200, False)


def test_poison_burn_and_reflection_styles_have_distinct_round_effects() -> None:
    poison = {
        "skill_key": "skill.test.poison",
        "effect": {"type": "physical_damage_multiplier_bp", "value": 12_000},
        "combat_style": {
            "key": "poison",
            "effect": {
                "damage_over_time_bp": 1_500,
                "enemy_attack_reduction_bp": 2_500,
                "duration_rounds": 2,
            },
        },
    }
    poison_state: dict[str, object] = {}
    assert apply_player_skill_style(
        poison, poison_state, round_no=1, player_attack=100, hit=True, enemy_acted=False
    ) == 0
    assert mitigate_enemy_attack(100, poison_state, round_no=1) == 75
    assert apply_player_skill_style(
        poison, poison_state, round_no=2, player_attack=100, hit=False, enemy_acted=False
    ) == 15
    assert mitigate_enemy_attack(100, poison_state, round_no=3) == 100

    burn = {
        "skill_key": "skill.test.burn",
        "effect": {"type": "spell_damage_multiplier_bp", "value": 10_000},
        "combat_style": {
            "key": "burn",
            "effect": {"damage_over_time_bp": 1_500, "duration_rounds": 2},
        },
    }
    burn_state: dict[str, object] = {}
    apply_player_skill_style(
        burn,
        burn_state,
        round_no=1,
        player_attack=100,
        hit=True,
        enemy_acted=False,
        direct_damage=200,
    )
    assert apply_player_skill_style(
        burn, burn_state, round_no=2, player_attack=100, hit=False, enemy_acted=False
    ) == 30

    reflect = {
        "skill_key": "skill.test.reflect",
        "effect": {"type": "physical_damage_multiplier_bp", "value": 10_000},
        "combat_style": {
            "key": "reflect",
            "effect": {"damage_reflection_bp": 2_500, "duration_rounds": 2},
        },
    }
    reflect_state: dict[str, object] = {"manual_reflect_damage_bp": 1_000}
    apply_player_skill_style(
        reflect, reflect_state, round_no=1, player_attack=100, hit=True, enemy_acted=False
    )
    assert reflected_enemy_damage(100, reflect_state, round_no=1) == 35
    assert reflected_enemy_damage(100, reflect_state, round_no=3) == 10
