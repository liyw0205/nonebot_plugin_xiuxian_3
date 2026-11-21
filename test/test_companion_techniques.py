from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.companion_techniques import (
    apply_companion_techniques,
)
from nonebot_plugin_xiuxian_3.xiuxian.companions.technique_content import (
    companion_technique_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp

ROOT = Path(__file__).parents[1]


def _context(
    adapter: str, user: str, request_id: str, operation_id: str = ""
) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
    )


async def _evolved_rat(runtime, adapter: str, user: str) -> str:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET location_key='xuantian.outskirts', spirit_stones=1000, "
            "inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"item.ancient_fruit": 3}), adapter, user),
        )
    bonded = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{user}-bond", f"{user}-bond"),
        "结缘灵兽 beast.wood_rat",
    )
    assert bonded.code == "COMPANION_BONDED", (bonded.code, bonded.message)
    instance_id = str(bonded.data["instance_id"])
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE companion_instances SET level=10, affinity=40, deployed=1 "
            "WHERE instance_id=?",
            (instance_id,),
        )
    evolved = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{user}-evolve", f"{user}-evolve"),
        f"蜕变灵兽 {instance_id}",
    )
    assert evolved.code == "COMPANION_EVOLVED", (evolved.code, evolved.message)
    assert evolved.data["companion_key"] == "beast.iron_rat"
    return instance_id


def _prepare_combat_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
            "location_key='xuantian.outskirts', stamina=100, stamina_max=100, max_hp=999, "
            "initiative=99, qualification_json=? WHERE platform=? AND platform_user_id=?",
            (
                json.dumps(
                    {
                        "body": 10,
                        "spirit": 10,
                        "insight": 10,
                        "root": 10,
                        "agility": 10,
                        "fortune": 10,
                    }
                ),
                adapter,
                user,
            ),
        )


def _equip_command(runtime, adapter: str, user: str, instance_id: str, operation: str):
    return runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{operation}-request", operation),
        f"装配灵兽战技 {instance_id} 1 踏风先声",
    )


def test_official_companion_technique_content_is_exact_and_closed() -> None:
    definitions = companion_technique_definitions(ContentBundle.load(ROOT / "data"))

    assert set(definitions) == {
        "technique.beast.rat_first_strike",
        "technique.beast.rat_root_guard",
        "technique.beast.jade_resonance",
    }
    assert definitions["technique.beast.rat_first_strike"].compatible_species == (
        "beast.iron_rat",
        "beast.jade_rat",
    )
    assert definitions["technique.beast.rat_first_strike"].effect == {
        "type": "opening_attack_bp",
        "value": 1800,
    }
    assert definitions["technique.beast.rat_root_guard"].effect == {
        "type": "first_guard_bp",
        "value": 1500,
    }
    assert definitions["technique.beast.jade_resonance"].slot_no == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update(key="technique.beast.侠"),
        lambda row: row.update(compatible_species=["mount.bamboo_deer"]),
        lambda row: row.update(slot_no=3),
        lambda row: row.update(unlock_evolution_key="mount.evolution.bamboo_deer_1"),
        lambda row: row.update(effect={"type": "client_damage", "value": 1}),
        lambda row: row.update(effect={"type": "opening_attack_bp", "value": True}),
        lambda row: row.update(extra="not permitted"),
    ],
)
def test_companion_technique_content_rejects_invalid_contract(tmp_path, mutate) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir)
    path = data_dir / "灵兽" / "战技.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document["records"][0])
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError):
        ContentBundle.load(data_dir)


def test_companion_technique_content_rejects_duplicate_keys(tmp_path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir)
    path = data_dir / "灵兽" / "战技.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][1]["key"] = document["records"][0]["key"]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentError, match="duplicate content key"):
        ContentBundle.load(data_dir)


def test_companion_technique_effects_are_capped_and_trigger_once() -> None:
    companions = [
        {
            "kind": "beast",
            "techniques": [
                {
                    "technique_key": "technique.one",
                    "name": "first",
                    "effect": {"type": "opening_attack_bp", "value": 3000},
                },
                {
                    "technique_key": "technique.two",
                    "name": "second",
                    "effect": {"type": "opening_attack_bp", "value": 3000},
                },
                {
                    "technique_key": "technique.guard",
                    "name": "guard",
                    "effect": {"type": "first_guard_bp", "value": 2500},
                },
            ],
        },
        {"kind": "mount", "techniques": []},
    ]
    changed, events, used = apply_companion_techniques(
        companions, trigger="first_attack", amount=100, used=set()
    )
    assert changed == 150
    assert len(events) == 2
    assert all(item["combined_bp"] == 5000 for item in events)
    assert used == {"technique.one", "technique.two"}

    repeated, repeated_events, repeated_used = apply_companion_techniques(
        companions, trigger="first_attack", amount=100, used=used
    )
    assert repeated == 100 and repeated_events == [] and repeated_used == used

    guarded, guard_events, guard_used = apply_companion_techniques(
        companions, trigger="first_received_damage", amount=100, used=used
    )
    assert guarded == 75
    assert guard_events[0]["technique_key"] == "technique.guard"
    assert guard_events[0]["amount_changed"] == 25
    assert guard_used == used | {"technique.guard"}


def test_shared_commands_bond_evolve_preview_equip_remove_and_retry() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            runtime = create_runtime(data_dir=data_dir)
            instances: dict[str, str] = {}
            for adapter, user in (
                ("qq.official", "technique-qq"),
                ("onebot.v11", "technique-onebot"),
            ):
                instance_id = await _evolved_rat(runtime, adapter, user)
                instances[adapter] = instance_id
                preview = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-preview"),
                    f"灵兽战技 {instance_id}",
                )
                assert preview.code == "COMPANION_TECHNIQUE_PREVIEW"
                assert preview.data["slots"][0]["open"] is True
                assert {row["key"] for row in preview.data["choices"]} == {
                    "technique.beast.rat_first_strike",
                    "technique.beast.rat_root_guard",
                }
                help_page = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-help"),
                    "修仙帮助 生活",
                )
                assert help_page.code == "HELP_CATEGORY"
                assert "[灵兽战技](command:" in help_page.message
                assert "[装配灵兽战技](command:" in help_page.message
                assert "[卸下灵兽战技](command:" in help_page.message
                assert "填写灵兽编号可预览灵窍与战技" in help_page.message

                concurrent_equips = await asyncio.gather(
                    _equip_command(runtime, adapter, user, instance_id, f"{user}-equip"),
                    _equip_command(runtime, adapter, user, instance_id, f"{user}-equip"),
                )
                assert all(row.code == "COMPANION_TECHNIQUE_EQUIPPED" for row in concurrent_equips)
                assert sum(bool(row.data["idempotent_replay"]) for row in concurrent_equips) == 1
                equipped = concurrent_equips[0]
                assert equipped.code == "COMPANION_TECHNIQUE_EQUIPPED"
                assert equipped.data["technique_key"] == "technique.beast.rat_first_strike"
                if adapter == "qq.official":
                    technique_path = data_dir / "灵兽" / "战技.json"
                    document = json.loads(technique_path.read_text(encoding="utf-8"))
                    document["records"][0]["status"] = "locked"
                    technique_path.write_text(
                        json.dumps(document, ensure_ascii=False), encoding="utf-8"
                    )
                    runtime.repository.content = ContentBundle.load(data_dir)
                    closed_preview = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{user}-preview-closed"),
                        f"灵兽战技 {instance_id}",
                    )
                    assert closed_preview.data["slots"][0]["content_available"] is False
                    assert all(
                        row["key"] != "technique.beast.rat_first_strike"
                        for row in closed_preview.data["choices"]
                    )
                    closed_equip = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{user}-equip-closed", f"{user}-closed-equip"),
                        f"装配灵兽战技 {instance_id} 1 踏风先声",
                    )
                    assert closed_equip.code == "COMPANION_TECHNIQUE_UNAVAILABLE"
                    replay_when_closed = await _equip_command(
                        runtime, adapter, user, instance_id, f"{user}-equip"
                    )
                    assert replay_when_closed.data["idempotent_replay"] is True
                    document["records"][0]["status"] = "active"
                    technique_path.write_text(
                        json.dumps(document, ensure_ascii=False), encoding="utf-8"
                    )
                    runtime.repository.content = ContentBundle.load(data_dir)
                conflict = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-conflict", f"{user}-equip"),
                    f"装配灵兽战技 {instance_id} 1 根甲护主",
                )
                assert conflict.code == "OPERATION_CONFLICT"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stored = connection.execute(
                        "SELECT slot_no, technique_key FROM companion_technique_loadouts "
                        "WHERE companion_instance_id=(SELECT id FROM companion_instances WHERE instance_id=?)",
                        (instance_id,),
                    ).fetchall()
                assert stored == [(1, "technique.beast.rat_first_strike")]

                removed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-remove", f"{user}-remove"),
                    f"卸下灵兽战技 {instance_id} 1",
                )
                assert removed.code == "COMPANION_TECHNIQUE_REMOVED"
                removed_retry = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{user}-remove-retry", f"{user}-remove"),
                    f"卸下灵兽战技 {instance_id} 1",
                )
                assert removed_retry.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM companion_technique_loadouts "
                        "WHERE companion_instance_id=(SELECT id FROM companion_instances WHERE instance_id=?)",
                        (instance_id,),
                    ).fetchone()[0] == 0

            wrong_owner = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "technique-onebot", "foreign"),
                f"灵兽战技 {instances['qq.official']}",
            )
            assert wrong_owner.code == "COMPANION_NOT_FOUND"
            readonly = await runtime.dispatch(
                CommandContext(
                    adapter="onebot.v11",
                    user_id="technique-onebot",
                    can_write_assets=False,
                    operation_id="readonly-equip",
                ),
                f"装配灵兽战技 {instances['onebot.v11']} 1 踏风先声",
            )
            assert readonly.code == "INVALID_CONTEXT"
            bad_arity = await runtime.adapters.dispatch(
                "qq.official",
                _context("qq.official", "technique-qq", "bad-arity"),
                f"装配灵兽战技 {instances['qq.official']} 1",
            )
            assert bad_arity.code == "INVALID_COMPANION_COMMAND"
            closed_slot = await runtime.adapters.dispatch(
                "qq.official",
                _context("qq.official", "technique-qq", "closed-slot"),
                f"装配灵兽战技 {instances['qq.official']} 2 青玉共鸣",
            )
            assert closed_slot.code == "COMPANION_TECHNIQUE_SLOT"
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            after_restart = await _equip_command(
                runtime,
                "qq.official",
                "technique-qq",
                instances["qq.official"],
                "technique-qq-equip",
            )
            assert after_restart.code == "COMPANION_TECHNIQUE_EQUIPPED"
            assert after_restart.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM companion_technique_loadouts "
                    "WHERE companion_instance_id=(SELECT id FROM companion_instances WHERE instance_id=?)",
                    (instances["qq.official"],),
                ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_companion_technique_schema_migration_is_forward_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "technique-schema-migration"
            instance_id = await _evolved_rat(runtime, adapter, user)
            with runtime.repository._connect() as connection:
                player_before = tuple(
                    connection.execute(
                        "SELECT player_id, spirit_stones, inventory_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                )
                companion_before = tuple(
                    connection.execute(
                        "SELECT instance_id, companion_key, level, affinity, evolution_stage, skill_slots "
                        "FROM companion_instances WHERE instance_id=?",
                        (instance_id,),
                    ).fetchone()
                )
                operations_before = tuple(
                    connection.execute(
                        "SELECT operation_id, operation_name, request_hash, result_json "
                        "FROM operations ORDER BY operation_id"
                    ).fetchall()
                )
                connection.execute("DROP TABLE companion_technique_loadouts")
                runtime.repository._migrate_companion_schema(connection)
                runtime.repository._migrate_companion_schema(connection)
                assert connection.execute(
                    "SELECT COUNT(*) FROM companion_technique_loadouts"
                ).fetchone()[0] == 0
                assert tuple(
                    connection.execute(
                        "SELECT player_id, spirit_stones, inventory_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                ) == player_before
                assert tuple(
                    connection.execute(
                        "SELECT instance_id, companion_key, level, affinity, evolution_stage, skill_slots "
                        "FROM companion_instances WHERE instance_id=?",
                        (instance_id,),
                    ).fetchone()
                ) == companion_before
                assert tuple(
                    connection.execute(
                        "SELECT operation_id, operation_name, request_hash, result_json "
                        "FROM operations ORDER BY operation_id"
                    ).fetchall()
                ) == operations_before
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(companion_technique_loadouts)"
                    )
                }
                assert {
                    "player_id",
                    "companion_instance_id",
                    "slot_no",
                    "technique_key",
                    "operation_id",
                } <= columns

            await runtime.close()
            restarted = create_runtime(data_dir=data_dir)
            await restarted.repository.initialize()
            with restarted.repository._connect() as connection:
                assert connection.execute(
                    "SELECT companion_key FROM companion_instances WHERE instance_id=?",
                    (instance_id,),
                ).fetchone()[0] == "beast.iron_rat"
                assert connection.execute(
                    "SELECT COUNT(*) FROM companion_technique_loadouts"
                ).fetchone()[0] == 0
            await restarted.close()

    asyncio.run(run())


def test_exploration_freezes_companion_technique_and_replay_survives_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "technique-exploration"
            instance_id = await _evolved_rat(runtime, adapter, user)
            _prepare_combat_player(runtime, adapter, user)
            equipped = await _equip_command(runtime, adapter, user, instance_id, "exp-equip")
            assert equipped.code == "COMPANION_TECHNIQUE_EQUIPPED"

            operation_id = next(
                f"technique-explore-{index}"
                for index in range(1000)
                if battle_roll_bp(f"technique-explore-{index}:battle") < 1000
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "explore-start", operation_id),
                "开始探索 短历练",
            )
            assert started.code == "EXPLORATION_STARTED", (started.code, started.message)
            exploration_id = str(started.data["exploration_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot_text = connection.execute(
                    "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                    (exploration_id,),
                ).fetchone()[0]
                exploration_snapshot = json.loads(snapshot_text)
                assert exploration_snapshot["companions"][0]["techniques"][0]["technique_key"] == (
                    "technique.beast.rat_first_strike"
                )
                connection.execute(
                    "UPDATE companion_technique_loadouts SET technique_key=? "
                    "WHERE companion_instance_id=(SELECT id FROM companion_instances WHERE instance_id=?)",
                    ("technique.beast.rat_root_guard", instance_id),
                )
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                        exploration_id,
                    ),
                )
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "explore-settle"),
                "结算探索",
            )
            assert settled.code == "EXPLORATION_SETTLED", (settled.code, settled.message)
            battle_id = str(settled.data["battle_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                        (battle_id,),
                    ).fetchone()[0]
                )
                action_events = [
                    json.loads(row[0])
                    for row in connection.execute(
                        "SELECT state_json FROM battle_actions WHERE battle_id=? "
                        "AND state_json LIKE '%companion_techniques%'",
                        (battle_id,),
                    ).fetchall()
                ]
            assert frozen["player"]["companions"][0]["techniques"][0]["technique_key"] == (
                "technique.beast.rat_first_strike"
            )
            assert action_events
            event = action_events[0]["companion_techniques"][0]
            assert event["technique_key"] == "technique.beast.rat_first_strike"
            assert event["trigger"] == "first_attack"
            assert event["amount_changed"] > 0

            await runtime.close()
            recovered = create_runtime(data_dir=data_dir)
            replay = await recovered.repository.replay_battle(
                platform=adapter, platform_user_id=user, battle_id=battle_id
            )
            replay_event = next(
                item
                for action in replay.actions
                for item in action["state"].get("companion_techniques", [])
            )
            assert replay_event == event
            await recovered.close()

    asyncio.run(run())


def test_standard_party_freezes_only_each_members_techniques_and_replays() -> None:
    async def create_standard_member(
        runtime, adapter: str, user: str, *, already_created: bool = False
    ) -> None:
        if not already_created:
            created = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, f"{user}-create"), "开始修仙"
            )
            assert created.code == "PLAYER_CREATED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='mortal', realm_layer=0, "
                "location_key='xuantian.outskirts', stamina=100, stamina_max=100, "
                "max_hp=999, initiative=99, qualification_json=? "
                "WHERE platform=? AND platform_user_id=?",
                (
                    json.dumps(
                        {
                            "body": 10,
                            "spirit": 10,
                            "insight": 10,
                            "root": 10,
                            "agility": 10,
                            "fortune": 10,
                        }
                    ),
                    adapter,
                    user,
                ),
            )

    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            runtime = create_runtime(data_dir=data_dir)
            members = (
                ("qq.official", "technique-party-leader"),
                ("onebot.v11", "technique-party-two"),
                ("qq.official", "technique-party-three"),
                ("onebot.v11", "technique-party-four"),
            )
            leader_adapter, leader = members[0]
            instance_id = await _evolved_rat(runtime, leader_adapter, leader)
            await create_standard_member(
                runtime, leader_adapter, leader, already_created=True
            )
            equipped = await _equip_command(
                runtime, leader_adapter, leader, instance_id, "party-technique-equip"
            )
            assert equipped.code == "COMPANION_TECHNIQUE_EQUIPPED"
            for adapter, user in members[1:]:
                await create_standard_member(runtime, adapter, user)

            created = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-create"),
                "创建四人副本队伍",
            )
            assert created.code == "PARTY_CREATED", (created.code, created.message)
            party_id = str(created.data["party_id"])
            for index, (adapter, user) in enumerate(members[1:], start=1):
                invited = await runtime.adapters.dispatch(
                    leader_adapter,
                    _context(leader_adapter, leader, f"party-invite-{index}"),
                    f"邀请入队 {adapter}:{user}",
                )
                assert invited.code == "PARTY_INVITED"
                accepted = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"party-accept-{index}"),
                    f"接受入队 {party_id}",
                )
                assert accepted.code == "PARTY_JOINED"
            for index, (adapter, user) in enumerate(members):
                confirmed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"party-confirm-{index}"),
                    f"确认入队 {party_id}",
                )
                assert confirmed.code in {"PARTY_CONFIRMED", "PARTY_READY"}

            with sqlite3.connect(runtime.settings.database_path) as connection:
                leader_database_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (leader_adapter, leader),
                ).fetchone()[0]
            started = await runtime.repository.start_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                party_id=party_id,
                operation_id="party-technique-start",
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?",
                        (started.battle_id,),
                    ).fetchone()[0]
                )
                member_by_database_id = {
                    int(member["database_id"]): member for member in snapshot["members"]
                }
                owner_snapshot = member_by_database_id[int(leader_database_id)]
                assert owner_snapshot["companions"][0]["techniques"][0]["technique_key"] == (
                    "technique.beast.rat_first_strike"
                )
                assert owner_snapshot["companions"][0]["techniques"][0]["effect"]["value"] == 1800
                assert all(
                    not member["companions"]
                    for member in snapshot["members"]
                    if int(member["database_id"]) != int(leader_database_id)
                )
            locked_remove = await runtime.adapters.dispatch(
                leader_adapter,
                _context(
                    leader_adapter,
                    leader,
                    "party-technique-remove-locked",
                    "party-technique-remove-locked",
                ),
                f"卸下灵兽战技 {instance_id} 1",
            )
            assert locked_remove.code == "COMPANION_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE companion_technique_loadouts SET technique_key=? "
                    "WHERE companion_instance_id=(SELECT id FROM companion_instances WHERE instance_id=?)",
                    ("technique.beast.rat_root_guard", instance_id),
                )
            technique_path = data_dir / "灵兽" / "战技.json"
            document = json.loads(technique_path.read_text(encoding="utf-8"))
            document["records"][0]["effect"]["value"] = 4000
            technique_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir)
            result = await runtime.repository.settle_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                battle_id=started.battle_id,
                operation_id="party-technique-settle",
            )
            assert result.outcome == "won", result.outcome
            replay = await runtime.repository.replay_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                battle_id=started.battle_id,
            )
            events = [
                event
                for action in replay.actions
                for event in json.loads(action["state_json"]).get("companion_techniques", [])
            ]
            assert events
            assert events[0]["technique_key"] == "technique.beast.rat_first_strike"
            assert events[0]["trigger"] == "first_attack"
            assert events[0]["value"] == 1800
            assert events[0]["amount_changed"] > 0

            party_view = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", members[1][1], "party-view-after"),
                "队伍状态",
            )
            assert party_view.code == "PARTY_PROFILE"
            rendered_data = json.dumps(party_view.data, ensure_ascii=False)
            assert instance_id not in rendered_data
            assert "technique.beast.rat_first_strike" not in rendered_data

            await runtime.close()
            recovered = create_runtime(data_dir=data_dir)
            replay_after_restart = await recovered.repository.replay_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                battle_id=started.battle_id,
            )
            replay_events = [
                event
                for action in replay_after_restart.actions
                for event in json.loads(action["state_json"]).get("companion_techniques", [])
            ]
            assert replay_events == events
            await recovered.close()

    asyncio.run(run())
