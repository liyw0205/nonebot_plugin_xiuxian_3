from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from combat_fixtures import equip_damage_weapon
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.party_rules import party_enemy_for_location
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


ADAPTERS = ("qq.official", "onebot.v11")


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    (target / "xiuxian3.sqlite3").unlink(missing_ok=True)
    return target


def _update_enemy(data_dir: Path, *, reward: dict[str, int]) -> None:
    path = data_dir / "战斗" / "敌人.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in document["records"] if item["key"] == "enemy.wood_rat")
    row["combat_profile"]["party_profile"]["reward"] = reward
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create:{user}"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"seek:{user}"), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='mortal', realm_layer=0, "
            "location_key='xuantian.outskirts', stamina=100, stamina_max=100, "
            "max_hp=999, initiative=99, spirit_stones=0, inventory_json='{}' "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
    equip_damage_weapon(runtime, adapter, user, 1000)


async def _make_party(runtime) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    members = (
        ("qq.official", "party-content-leader"),
        ("onebot.v11", "party-content-two"),
        ("qq.official", "party-content-three"),
        ("onebot.v11", "party-content-four"),
    )
    for adapter, user in members:
        await _create_player(runtime, adapter, user)
    leader_adapter, leader = members[0]
    created = await runtime.adapters.dispatch(
        leader_adapter,
        _context(leader_adapter, leader, "party-content-create"),
        "创建四人副本队伍",
    )
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    for index, (adapter, user) in enumerate(members[1:], start=1):
        invited = await runtime.adapters.dispatch(
            leader_adapter,
            _context(leader_adapter, leader, f"party-content-invite:{index}"),
            f"邀请入队 {adapter}:{user}",
        )
        assert invited.code == "PARTY_INVITED"
        accepted = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, f"party-content-accept:{index}"),
            f"接受入队 {party_id}",
        )
        assert accepted.code == "PARTY_JOINED"
    for index, (adapter, user) in enumerate(members):
        confirmed = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, f"party-content-confirm:{index}"),
            f"确认入队 {party_id}",
        )
        assert confirmed.code in {"PARTY_CONFIRMED", "PARTY_READY"}
    return leader_adapter, leader, party_id, members


def test_standard_party_enemy_and_reward_are_loaded_from_content(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        _update_enemy(data_dir, reward={"cultivation": 31, "spirit_stones": 11})
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            leader_adapter, leader, party_id, members = await _make_party(runtime)
            started = await runtime.repository.start_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                party_id=party_id,
                operation_id="party-content-start",
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?",
                        (started.battle_id,),
                    ).fetchone()[0]
                )
            assert snapshot["enemy"]["key"] == "enemy.wood_rat"
            assert snapshot["reward"] == {"cultivation": 31, "spirit_stones": 11}
        finally:
            await runtime.close()

        _update_enemy(data_dir, reward={"cultivation": 99, "spirit_stones": 99})
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            settled = await recovered.repository.settle_party_battle(
                platform=members[1][0],
                platform_user_id=members[1][1],
                battle_id=started.battle_id,
                operation_id="party-content-settle",
            )
            assert settled.outcome == "won"
            assert all(
                reward == {"cultivation": 31, "spirit_stones": 11}
                for reward in settled.rewards.values()
            )
            replay = await recovered.repository.settle_party_battle(
                platform=members[1][0],
                platform_user_id=members[1][1],
                battle_id=started.battle_id,
                operation_id="party-content-settle",
            )
            assert replay.already_completed is True
        finally:
            await recovered.close()

    asyncio.run(run())


def test_standard_party_content_rejects_invalid_reward_before_runtime_use(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    _update_enemy(data_dir, reward={"cultivation": -1})
    with pytest.raises(ContentError):
        party_enemy_for_location(
            "xuantian.outskirts", content=ContentBundle.load(data_dir)
        )


def test_standard_party_content_rejects_multiple_enemies_at_one_location(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    path = data_dir / "战斗" / "敌人.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    original = next(item for item in document["records"] if item["key"] == "enemy.wood_rat")
    duplicate = json.loads(json.dumps(original, ensure_ascii=False))
    duplicate["key"] = "enemy.wood_rat_duplicate"
    duplicate["name"] = "木鼠群"
    document["records"].append(duplicate)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ContentError, match="multiple enemies"):
        party_enemy_for_location(
            "xuantian.outskirts", content=ContentBundle.load(data_dir)
        )
