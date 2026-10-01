from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.three_realms_tower_rules import (
    MAX_FLOOR,
    NASCENT_SOUL_MAX_FLOOR,
    enemy_key_for,
    floor_definition,
    rebuild_reputation_total,
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


def test_three_realms_tower_rules_are_faction_specific() -> None:
    assert MAX_FLOOR == 40
    assert NASCENT_SOUL_MAX_FLOOR == 20
    assert floor_definition(1).stamina_cost == 12
    assert floor_definition(20).weekly_limit == 2
    assert floor_definition(21).required_realm == "soul_transformation"
    assert floor_definition(40).required_realm == "soul_transformation"
    assert rebuild_reputation_total(
        {"local.domain_refuge": 200, "local.abyss_outpost": 200, "local.ancestral_habitat": 100}
    ) == 500
    assert reward_for(1, "seed", first_clear=True) == {
        "item.mat.array_sand": 2,
        "spirit_stones": 60,
    }
    assert reward_for(1, "seed", first_clear=False) in ({}, {"item.mat.array_sand": 1})
    for faction in ("xuantian", "demon", "beast"):
        for floor_no in range(1, MAX_FLOOR + 1):
            enemy = enemy_definition(enemy_key_for(floor_no, faction))
            assert enemy.location_key == "tower.three_realms"
            assert enemy.required_realm == "mortal"
            assert enemy.reward == {}
            if floor_no > NASCENT_SOUL_MAX_FLOOR:
                assert enemy.random_pool == f"battle.{enemy.key}"
        assert enemy_key_for(10, faction) == f"enemy.three_realms_tower.{faction}.floor_10_boss"
        assert enemy_key_for(20, faction) == f"enemy.three_realms_tower.{faction}.floor_20_boss"
        assert enemy_key_for(21, faction).endswith(".domain_vanguard")
        assert enemy_key_for(30, faction).endswith(".floor_30_boss")
        assert enemy_key_for(31, faction).endswith(".domain_veteran")
        assert enemy_key_for(40, faction).endswith(".floor_40_boss")


def _seed_tower_completion(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        player_id = db.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,starts_at,"
            "result_json,reward_json,created_at,updated_at) "
            "VALUES(?,?,'tower.three_realms',20,'claimed',1,?,'{}','{}',?,?)",
            (f"fixture-history-{adapter}-{user}", player_id, "2026-09-28T00:00:00+00:00", "2026-09-28T00:00:00+00:00", "2026-09-28T00:00:00+00:00"),
        )


def _make_tower_eligible(
    runtime, adapter: str, user: str, faction: str, *, realm: str, rebuild_reputation: int = 0
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator',realm_key=?,realm_layer=1,stamina=10000,"
            "stamina_max=10000,max_hp=50000,initiative=5000,pollution=17,bloodline_stability=61,"
            "qualification_json=?,intro_json=?,faction_reputation_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                realm,
                json.dumps({"body": 10000, "agility": 1000, "spirit": 100}),
                json.dumps({"flags": ["story.mainline.three_realms", f"alliance.{faction}"]}),
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
            (
                player_id,
                json.dumps({"local.domain_refuge": rebuild_reputation, "local.abyss_outpost": 0, "local.ancestral_habitat": 0}),
            ),
        )


def test_three_realms_tower_progression_on_qq_and_onebot(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user, faction, realm, reputation in (
                ("qq.official", "three-tower-gate-qq", "xuantian", "soul_transformation", 0),
                ("onebot.v11", "three-tower-gate-onebot", "beast", "nascent_soul", 499),
            ):
                prefix = adapter.replace(".", "-")
                assert (await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")).ok
                _make_tower_eligible(
                    runtime, adapter, user, faction, realm=realm, rebuild_reputation=reputation
                )
                _seed_tower_completion(runtime, adapter, user)
                preview = await _send(runtime, adapter, user, f"{prefix}-preview", "三界塔")
                assert preview.code == "THREE_REALMS_TOWER_PREVIEW"
                assert preview.data["next_floor"] == 21

                if adapter == "qq.official":
                    original = runtime.repository.start_quest_battle

                    async def fail_start(**kwargs):
                        raise RuntimeError("simulated battle-start failure")

                    monkeypatch.setattr(runtime.repository, "start_quest_battle", fail_start)
                    aborted = await _send(
                        runtime, adapter, user, f"{prefix}-abort-21", "挑战三界塔 21"
                    )
                    assert aborted.code == "THREE_REALMS_TOWER_START_FAILED"
                    monkeypatch.setattr(runtime.repository, "start_quest_battle", original)
                    with sqlite3.connect(runtime.settings.database_path) as db:
                        status, stamina = db.execute(
                            "SELECT t.status,p.stamina FROM tower_runs t JOIN players p ON p.id=t.player_id "
                            "WHERE t.player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                            "AND t.floor_no=21 ORDER BY t.id DESC LIMIT 1",
                            (adapter, user),
                        ).fetchone()
                    assert status == "aborted"
                    assert stamina == 10000
                else:
                    denied = await _send(
                        runtime, adapter, user, f"{prefix}-gate-21", "挑战三界塔 21"
                    )
                    assert denied.code == "THREE_REALMS_TOWER_REQUIREMENT_MISSING"
                    with sqlite3.connect(runtime.settings.database_path) as db:
                        assert db.execute(
                            "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0] == 10000
                    # The mainline permit cannot bypass the rebuild threshold.
                    _make_tower_eligible(
                        runtime, adapter, user, faction, realm="nascent_soul", rebuild_reputation=500
                    )

                if adapter == "onebot.v11":
                    with sqlite3.connect(runtime.settings.database_path) as db:
                        db.execute(
                            "UPDATE players SET max_hp=1,initiative=0,qualification_json=? "
                            "WHERE platform=? AND platform_user_id=?",
                            (json.dumps({"body": 0, "agility": 0, "spirit": 0}), adapter, user),
                        )
                    loss = await _send(runtime, adapter, user, f"{prefix}-loss-21", "挑战三界塔 21")
                    assert loss.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED"
                    assert loss.data["outcome"] != "won"
                    _make_tower_eligible(
                        runtime, adapter, user, faction, realm="nascent_soul", rebuild_reputation=500
                    )

                for floor_no in range(21, 41):
                    challenged = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-floor-{floor_no}",
                        f"挑战三界塔 {floor_no}",
                    )
                    assert challenged.code == "THREE_REALMS_TOWER_CHALLENGE_SETTLED", (
                        adapter, floor_no, challenged.code, challenged.message
                    )
                    assert challenged.data["outcome"] == "won", (adapter, floor_no, challenged.data)
                    assert challenged.data["first_clear"] is True
                    if floor_no in {30, 40}:
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            snapshot_json = db.execute(
                                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                                (challenged.data["battle_id"],),
                            ).fetchone()[0]
                        snapshot = json.loads(snapshot_json)
                        assert snapshot["enemy"]["key"] == enemy_key_for(floor_no, faction)
                        assert snapshot["tower_context"]["faction"] == faction
                        assert snapshot["tower_context"]["pollution"] == 17
                        assert snapshot["tower_context"]["bloodline_stability"] == 61

                    claim = await _send(
                        runtime, adapter, user, f"{prefix}-claim-{floor_no}", "领取三界塔奖励"
                    )
                    assert claim.code == "THREE_REALMS_TOWER_REWARD_CLAIMED"
                    assert claim.data["first_clear"] is True
                    assert claim.data["reward"] == {
                        "item.mat.array_sand": 2,
                        "spirit_stones": 60,
                    }
                    if floor_no == 21:
                        replay = await _send(
                            runtime, adapter, user, f"{prefix}-floor-21", "挑战三界塔 21"
                        )
                        claim_replay = await _send(
                            runtime, adapter, user, f"{prefix}-claim-21", "领取三界塔奖励"
                        )
                        assert replay.data["idempotent_replay"] is True
                        assert claim_replay.data["idempotent_replay"] is True
                    if floor_no in {30, 40}:
                        story_kind = "reconstruction" if floor_no == 30 else "domain"
                        story_entry = f"codex.story.three_realms.{story_kind}_{faction}"
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            entry = db.execute(
                                "SELECT c.payload_json FROM codex_entries c "
                                "JOIN players p ON p.id=c.player_id WHERE p.platform=? AND p.platform_user_id=? "
                                "AND c.entry_key=?",
                                (adapter, user, story_entry),
                            ).fetchone()
                        assert entry is not None
                        assert json.loads(entry[0])["faction"] == faction

                    if floor_no == 21 and adapter == "qq.official":
                        practice = await _send(
                            runtime, adapter, user, f"{prefix}-practice-21", "挑战三界塔 21"
                        )
                        assert practice.data["first_clear"] is False
                        assert practice.data["reward"].get("spirit_stones", 0) == 0
                        assert practice.data["reward"].get("item.mat.array_sand", 0) in {0, 1}
                        practice_claim = await _send(
                            runtime, adapter, user, f"{prefix}-practice-claim-21", "领取三界塔奖励"
                        )
                        assert practice_claim.ok
                        capped = await _send(
                            runtime, adapter, user, f"{prefix}-cap-21", "挑战三界塔 21"
                        )
                        assert capped.code == "THREE_REALMS_TOWER_WEEKLY_CAP"
                    elif floor_no == 21 and adapter == "onebot.v11":
                        capped = await _send(
                            runtime, adapter, user, f"{prefix}-cap-21", "挑战三界塔 21"
                        )
                        assert capped.code == "THREE_REALMS_TOWER_WEEKLY_CAP"

                honors = await _send(runtime, adapter, user, f"{prefix}-honors", "功业录")
                assert honors.code == "HONOR_STATUS"
                title = next(
                    item for item in honors.data["titles"]
                    if item["title_key"] == "title.three_realms_tower.domain_guardian"
                )
                assert title["acquired"] is True
                with sqlite3.connect(runtime.settings.database_path) as db:
                    high_floor_count = db.execute(
                        "SELECT COUNT(*) FROM tower_reward_claims c JOIN players p ON p.id=c.player_id "
                        "WHERE p.platform=? AND p.platform_user_id=? AND c.floor_no BETWEEN 21 AND 40",
                        (adapter, user),
                    ).fetchone()[0]
                    battles_with_rewards = db.execute(
                        "SELECT COUNT(*) FROM battle_sessions b JOIN tower_runs t ON t.battle_id=b.battle_id "
                        "WHERE t.player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "AND t.tower_key='tower.three_realms' AND b.reward_status<>'none'",
                        (adapter, user),
                    ).fetchone()[0]
                assert high_floor_count == 20 + (adapter == "qq.official")
                assert battles_with_rewards == 0
            await runtime.close()

    asyncio.run(run())


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
                for floor_no in range(1, NASCENT_SOUL_MAX_FLOOR + 1):
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
                                "SELECT c.payload_json FROM codex_entries c "
                                "JOIN players p ON p.id=c.player_id WHERE p.platform=? AND p.platform_user_id=? "
                                "AND c.entry_key=?",
                                (adapter, user, story_entry),
                            ).fetchone()
                        assert entry is not None
                        assert json.loads(entry[0])["faction"] == faction
                        assert json.loads(entry[0])["pollution"] == 17
                        assert json.loads(entry[0])["bloodline_stability"] == 61

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
                    assert player[1] == 60 * NASCENT_SOUL_MAX_FLOOR
                    inventory = json.loads(player[2])
                    assert inventory["item.mat.array_sand"] >= 2 * NASCENT_SOUL_MAX_FLOOR
                    assert db.execute(
                        "SELECT COUNT(*) FROM tower_runs WHERE player_id=(SELECT id FROM players "
                        "WHERE platform=? AND platform_user_id=?) AND tower_key='tower.three_realms'",
                        (adapter, user),
                    ).fetchone()[0] == NASCENT_SOUL_MAX_FLOOR + 1
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
                    ).fetchone()[0] == NASCENT_SOUL_MAX_FLOOR

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
