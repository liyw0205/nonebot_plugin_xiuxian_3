from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.three_realms_tower_rules import (
    CONTENT_VERSION,
    MAX_FLOOR,
    RULE_VERSION,
    enemy_key_for,
    floor_definition,
    reward_for,
)


async def _send(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation),
        command,
    )


def _make_eligible(runtime, adapter: str, user: str, faction: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator',realm_key='nascent_soul',realm_layer=1,"
            "stamina=10000,stamina_max=10000,max_hp=600,initiative=0,"
            "pollution=17,bloodline_stability=61,"
            "qualification_json=?,intro_json=?,faction_reputation_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"body": 15, "agility": 15}),
                json.dumps({"flags": [f"alliance.{faction}"]}),
                json.dumps({faction: 500}),
                adapter,
                user,
            ),
        )
        player_id = db.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
            "VALUES (?,?,0,'2026-09-28T00:00:00+00:00') "
            "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,updated_at=excluded.updated_at",
            (player_id, json.dumps({"local.xuantian.new_town": 23})),
        )


def test_three_realms_tower_rules_are_versioned_and_faction_specific() -> None:
    assert MAX_FLOOR == 20
    assert floor_definition(1).stamina_cost == 12
    assert floor_definition(20).weekly_limit == 2
    assert reward_for(1, "seed", first_clear=True) == {
        "item.mat.array_sand": 2,
        "spirit_stones": 60,
    }
    assert reward_for(1, "seed", first_clear=False) in ({}, {"item.mat.array_sand": 1})
    for faction in ("xuantian", "demon", "beast"):
        key = enemy_key_for(10, faction)
        assert key == f"enemy.three_realms_tower.{faction}.floor_10_boss"
        enemy = enemy_definition(key)
        assert enemy.location_key == "tower.three_realms"
        assert enemy.required_realm == "mortal"
        assert enemy.reward == {}


def test_three_realms_tower_full_progression_on_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user, faction in (
                ("qq.official", "three-tower-qq", "xuantian"),
                ("onebot.v11", "three-tower-onebot", "demon"),
            ):
                prefix = adapter.replace(".", "-")
                created = await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")
                assert created.ok
                with sqlite3.connect(runtime.settings.database_path) as db:
                    initial_stamina = db.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                denied = await _send(runtime, adapter, user, f"{prefix}-gate-denied", "挑战三界塔 1")
                assert denied.code == "THREE_REALMS_TOWER_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    assert db.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0] == initial_stamina

                _make_eligible(runtime, adapter, user, faction)
                preview = await _send(runtime, adapter, user, f"{prefix}-preview", "三界塔")
                assert preview.code == "THREE_REALMS_TOWER_PREVIEW"
                assert preview.data["next_floor"] == 1

                locked = await _send(runtime, adapter, user, f"{prefix}-locked", "挑战三界塔 2")
                assert locked.code == "THREE_REALMS_TOWER_FLOOR_LOCKED"
                for floor_no in range(1, MAX_FLOOR + 1):
                    operation = f"{prefix}-floor-{floor_no}"
                    challenged = await _send(
                        runtime, adapter, user, operation, f"挑战三界塔 {floor_no}"
                    )
                    assert challenged.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED", (
                        adapter, floor_no, challenged.code, challenged.message
                    )
                    assert challenged.data["outcome"] == "won", (adapter, floor_no, challenged.data)
                    assert challenged.data["first_clear"] is True
                    if floor_no in {10, 20}:
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            snapshot_json = db.execute(
                                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                                (challenged.data["battle_id"],),
                            ).fetchone()[0]
                        snapshot = json.loads(snapshot_json)
                        assert snapshot["enemy"]["key"] == enemy_key_for(floor_no, faction)
                        assert snapshot["tower_key"] == "tower.three_realms"
                        assert snapshot["tower_floor"] == floor_no
                        assert snapshot["tower_context"]["faction"] == faction
                        assert snapshot["tower_context"]["alliance"] == faction
                        assert snapshot["tower_context"]["pollution"] == 17
                        assert snapshot["tower_context"]["bloodline_stability"] == 61
                        assert snapshot["tower_context"]["local_reputation"]["local.xuantian.new_town"] == 23
                        assert (snapshot["content_version"], snapshot["rule_version"]) == (
                            "content-0.3",
                            "combat-0.3.0",
                        )
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            settled = db.execute(
                                "SELECT t.result_json,e.payload_json FROM tower_runs t "
                                "LEFT JOIN activity_events e ON e.source_operation_id=? WHERE t.run_id=?",
                                (f"battle.resolve:{challenged.data['battle_id']}", challenged.data["run_id"]),
                            ).fetchone()
                        run_result, settlement_event = map(json.loads, settled)
                        assert run_result["tower_context"]["faction"] == faction
                        assert settlement_event["tower_context"]["local_reputation"][
                            "local.xuantian.new_town"
                        ] == 23

                    claim = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-claim-{floor_no}",
                        "领取三界塔奖励",
                    )
                    assert claim.code == "THREE_REALMS_TOWER_REWARD_CLAIMED"
                    assert claim.data["first_clear"] is True
                    assert claim.data["faction"] == faction
                    assert claim.data["reward"] == {
                        "item.mat.array_sand": 2,
                        "spirit_stones": 60,
                    }
                    if floor_no in {10, 20}:
                        story_entry = f"codex.story.three_realms.faction_{faction}"
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            entry = db.execute(
                                "SELECT c.payload_json,c.content_version,c.rule_version FROM codex_entries c "
                                "JOIN players p ON p.id=c.player_id WHERE p.platform=? AND p.platform_user_id=? "
                                "AND c.entry_key=?",
                                (adapter, user, story_entry),
                            ).fetchone()
                        assert entry is not None
                        assert json.loads(entry[0])["faction"] == faction
                        assert json.loads(entry[0])["pollution"] == 17
                        assert json.loads(entry[0])["bloodline_stability"] == 61
                        assert (entry[1], entry[2]) == (CONTENT_VERSION, RULE_VERSION)

                    if floor_no == 1:
                        replay = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-floor-1",
                            "挑战三界塔 1",
                        )
                        assert replay.data["idempotent_replay"] is True
                        operation_conflict = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-floor-1",
                            "挑战三界塔 2",
                        )
                        assert operation_conflict.code == "OPERATION_CONFLICT"
                        replay_claim = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-claim-1",
                            "领取三界塔奖励",
                        )
                        assert replay_claim.data["idempotent_replay"] is True
                        practice = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-practice-1",
                            "挑战三界塔 1",
                        )
                        assert practice.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
                        assert practice.data["first_clear"] is False
                        practice_claim = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-practice-claim-1",
                            "领取三界塔奖励",
                        )
                        assert practice_claim.code == "THREE_REALMS_TOWER_REWARD_CLAIMED"
                        capped = await _send(
                            runtime,
                            adapter,
                            user,
                            f"{prefix}-practice-2",
                            "挑战三界塔 1",
                        )
                        assert capped.code == "THREE_REALMS_TOWER_WEEKLY_CAP"

                with sqlite3.connect(runtime.settings.database_path) as db:
                    player = db.execute(
                        "SELECT cultivation,spirit_stones,inventory_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert player[0] == 0
                    assert player[1] == 60 * MAX_FLOOR
                    inventory = json.loads(player[2])
                    assert inventory["item.mat.array_sand"] >= 2 * MAX_FLOOR
                    assert db.execute(
                        "SELECT COUNT(*) FROM tower_runs WHERE player_id=(SELECT id FROM players "
                        "WHERE platform=? AND platform_user_id=?) AND tower_key='tower.three_realms'",
                        (adapter, user),
                    ).fetchone()[0] == MAX_FLOOR + 1
                    assert db.execute(
                        "SELECT COUNT(*) FROM battle_sessions b JOIN tower_runs t ON t.battle_id=b.battle_id "
                        "WHERE t.player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "AND t.tower_key='tower.three_realms' AND b.reward_status<>'none'",
                        (adapter, user),
                    ).fetchone()[0] == 0
                    assert db.execute(
                        "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                        "WHERE p.platform=? AND p.platform_user_id=? "
                        "AND c.entry_key LIKE 'codex.challenge.three_realms.floor_%'",
                        (adapter, user),
                    ).fetchone()[0] == MAX_FLOOR

            # A completed three-realms story permits a below-Yuan-ying character.
            adapter, user = "onebot.v11", "three-tower-story-permit"
            assert (await _send(runtime, adapter, user, "permit-create", "开始修仙")).ok
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET intro_json=?,qualification_json=?,stamina=100,stamina_max=100,"
                    "max_hp=20000,initiative=5000 WHERE platform=? AND platform_user_id=?",
                    (
                        json.dumps({"flags": ["story.mainline.three_realms", "alliance.beast"]}),
                        json.dumps({"body": 10000, "agility": 100}),
                        adapter,
                        user,
                    ),
                )
            permitted = await _send(runtime, adapter, user, "permit-run", "挑战三界塔 1")
            assert permitted.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_three_realms_tower_failed_attempt_counts_and_start_failure_refunds(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user, faction in (
                ("qq.official", "three-tower-loss-qq", "xuantian"),
                ("onebot.v11", "three-tower-loss-onebot", "beast"),
            ):
                prefix = adapter.replace(".", "-")
                assert (await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")).ok
                _make_eligible(runtime, adapter, user, faction)
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET max_hp=30,initiative=1,qualification_json=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"body": 0, "agility": 0}), adapter, user),
                    )
                lost = await _send(runtime, adapter, user, f"{prefix}-loss", "挑战三界塔 1")
                assert lost.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
                assert lost.data["outcome"] != "won"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    stamina_after_loss = db.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    assert stamina_after_loss == 10000 - 12

                _make_eligible(runtime, adapter, user, faction)
                won = await _send(runtime, adapter, user, f"{prefix}-retry", "挑战三界塔 1")
                assert won.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
                assert won.data["first_clear"] is True
                assert (await _send(runtime, adapter, user, f"{prefix}-claim", "领取三界塔奖励")).ok
                capped = await _send(runtime, adapter, user, f"{prefix}-capped", "挑战三界塔 1")
                assert capped.code == "THREE_REALMS_TOWER_WEEKLY_CAP"

            adapter, user = "qq.official", "three-tower-aborted"
            assert (await _send(runtime, adapter, user, "abort-create", "开始修仙")).ok
            _make_eligible(runtime, adapter, user, "xuantian")
            original = runtime.repository.start_quest_battle

            async def fail_start(**kwargs):
                raise RuntimeError("simulated battle-start failure")

            monkeypatch.setattr(runtime.repository, "start_quest_battle", fail_start)
            failed = await _send(runtime, adapter, user, "abort-run", "挑战三界塔 1")
            assert failed.code == "THREE_REALMS_TOWER_START_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                stamina = db.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
                status = db.execute(
                    "SELECT status FROM tower_runs WHERE player_id=(SELECT id FROM players "
                    "WHERE platform=? AND platform_user_id=?) AND tower_key='tower.three_realms'",
                    (adapter, user),
                ).fetchone()[0]
            assert stamina == 10000
            assert status == "aborted"
            monkeypatch.setattr(runtime.repository, "start_quest_battle", original)
            retry = await _send(runtime, adapter, user, "abort-retry", "挑战三界塔 1")
            assert retry.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
            assert retry.data["outcome"] == "won"
            await runtime.close()

    asyncio.run(run())
