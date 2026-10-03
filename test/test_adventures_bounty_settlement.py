from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import bounty_definitions


_ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"{user}:{name}",
        operation_id=operation_id,
    )


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_content(data_dir: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)


def _configure_fixed_herb_reward(data_dir: Path) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = _json(path)
    pool = next(row for row in document["records"] if row["key"] == "reward_pool.bounty.herb_supply")
    pool["outcomes"] = [{"weight": 1, "rewards": {"spirit_stones": 31, "local_reputation": 10}}]
    _write_json(path, document)


def _configure_gear_and_codex_reward(data_dir: Path) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = _json(path)
    pool = next(row for row in document["records"] if row["key"] == "reward_pool.bounty.herb_supply")
    pool["outcomes"] = [
        {
            "weight": 1,
            "rewards": {
                "item.weapon.body.pulse_edge": 1,
                "codex.story.beast_habitat": 1,
            },
        }
    ]
    _write_json(path, document)


async def _create_mortal(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, "create"), "开始修仙"
    )
    assert created.code == "PLAYER_CREATED"
    seeking = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, "seek"), "寻仙问道"
    )
    assert seeking.ok


def _set_local_reputation(runtime, adapter: str, user: str, value: object) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, 'test') ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, value),
        )


def _add_herbs(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        inventory_json = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        inventory = json.loads(inventory_json)
        inventory["item.herb.blood_grass"] = inventory.get("item.herb.blood_grass", 0) + 5
        connection.execute(
            "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, sort_keys=True), adapter, user),
        )


def _player_state(runtime, adapter: str, user: str) -> tuple[int, str, str, str | None]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT p.spirit_stones, p.inventory_json, o.status, r.local_json "
            "FROM players p JOIN bounty_offers o ON o.player_id=p.id "
            "LEFT JOIN player_reputations r ON r.player_id=p.id "
            "WHERE p.platform=? AND p.platform_user_id=?",
            (adapter, user),
        ).fetchone()
    return row[0], row[1], row[2], row[3]


def test_bounty_claim_uses_frozen_definition_reward_and_reputation_cap_after_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_fixed_herb_reward(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-freeze-{adapter}"
                    await _create_mortal(runtime, adapter, user)
                    _set_local_reputation(
                        runtime, adapter, user, '{"local.xuantian.new_town":995}'
                    )
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", f"{adapter}:bounty-accept"),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)
                await runtime.close()

                bounty_path = data_dir / "任务" / "悬赏.json"
                bounties = _json(bounty_path)
                herb = next(row for row in bounties["records"] if row["key"] == "bounty.herb_supply")
                herb.update(
                    {
                        "name": "改动后的榜单",
                        "desc": "改动后的目标",
                        "target_key": "item.material.cloud_iron",
                        "target_amount": 99,
                        "reward_pool_key": "reward_pool.bounty.craft_order",
                        "reputation_key": "local.xuantian.cloud_city",
                    }
                )
                _write_json(bounty_path, bounties)
                locations_path = data_dir / "地图" / "地点.json"
                locations = _json(locations_path)
                new_town = next(
                    row for row in locations["records"] if row["key"] == "xuantian.new_town"
                )
                new_town["local_reputation_maximum"] = 996
                _write_json(locations_path, locations)

                runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
                try:
                    for adapter in _ADAPTERS:
                        user = f"bounty-freeze-{adapter}"
                        board = await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, "board"), "悬赏榜"
                        )
                        offer = next(
                            row for row in board.data["offers"]
                            if row["bounty_key"] == "bounty.herb_supply"
                        )
                        assert offer["label"] == "草药补给"
                        assert offer["target"] == 5
                        assert offer["progress"] == 5
                        assert offer["reward"] == {
                            "spirit_stones": 31,
                            "local_reputation": 10,
                        }
                        claimed = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "claim", f"{adapter}:bounty-claim"),
                            "领取悬赏",
                        )
                        assert claimed.code == "BOUNTY_CLAIMED"
                        assert claimed.data["rewards"] == {
                            "spirit_stones": 31,
                            "local_reputation": 5,
                        }
                        assert "青石镇名望 +5" in claimed.message
                        replay = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "claim-replay", f"{adapter}:bounty-claim"),
                            "领取悬赏",
                        )
                        assert replay.data["idempotent_replay"] is True
                        assert replay.data["rewards"] == claimed.data["rewards"]
                        stones, inventory_json, status, reputation_json = _player_state(
                            runtime, adapter, user
                        )
                        assert stones >= 31
                        assert json.loads(inventory_json)["item.herb.blood_grass"] >= 5
                        assert status == "claimed"
                        assert json.loads(reputation_json)["local.xuantian.new_town"] == 1000
                finally:
                    await runtime.close()
            finally:
                await runtime.close()

    asyncio.run(run())


def test_bounty_claim_json_errors_and_ledger_failure_leave_offer_retryable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_fixed_herb_reward(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            operations = {}
            snapshots = {}
            balances = {}
            try:
                for index, adapter in enumerate(_ADAPTERS):
                    user = f"bounty-recovery-{adapter}"
                    operation_id = f"{adapter}:bounty-recovery-claim"
                    operations[adapter] = (user, operation_id)
                    await _create_mortal(runtime, adapter, user)
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", f"{adapter}:bounty-recovery-accept"),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.ok
                    _add_herbs(runtime, adapter, user)
                    _set_local_reputation(
                        runtime, adapter, user, '{"local.xuantian.new_town":995}'
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        balances[adapter] = connection.execute(
                            "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        snapshots[adapter] = connection.execute(
                            "SELECT snapshot_json FROM bounty_offers WHERE operation_id=?",
                            (f"{adapter}:bounty-recovery-accept",),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE bounty_offers SET snapshot_json='{' WHERE operation_id=?",
                            (f"{adapter}:bounty-recovery-accept",),
                        )
                    malformed_snapshot = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "bad-snapshot", operation_id),
                        "领取悬赏",
                    )
                    assert malformed_snapshot.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET snapshot_json=? WHERE operation_id=?",
                            (snapshots[adapter], f"{adapter}:bounty-recovery-accept"),
                        )

                    _set_local_reputation(runtime, adapter, user, "{malformed")
                    malformed_reputation = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "bad-reputation", operation_id),
                        "领取悬赏",
                    )
                    assert malformed_reputation.code == "PERSISTENCE_ERROR"
                    stones, inventory_json, status, reputation_json = _player_state(
                        runtime, adapter, user
                    )
                    assert status == "accepted"
                    assert reputation_json == "{malformed"
                    assert json.loads(inventory_json)["item.herb.blood_grass"] >= 5
                    assert stones == balances[adapter]
                    _set_local_reputation(
                        runtime, adapter, user, '{"local.xuantian.new_town":995}'
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            f"CREATE TRIGGER fail_bounty_claim_{index} BEFORE INSERT ON operations "
                            f"WHEN NEW.operation_id='{operation_id}' BEGIN "
                            "SELECT RAISE(ABORT, 'injected bounty ledger failure'); END"
                        )
                for adapter, (user, operation_id) in operations.items():
                    failed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "ledger-failure", operation_id),
                        "领取悬赏",
                    )
                    assert failed.code == "PERSISTENCE_ERROR"
                    stones, inventory_json, status, reputation_json = _player_state(
                        runtime, adapter, user
                    )
                    assert status == "accepted"
                    assert stones == balances[adapter]
                    assert json.loads(inventory_json)["item.herb.blood_grass"] >= 5
                    assert json.loads(reputation_json)["local.xuantian.new_town"] == 995
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0] == 0
                await runtime.close()
            finally:
                await runtime.close()

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER fail_bounty_claim_0")
                connection.execute("DROP TRIGGER fail_bounty_claim_1")
            recovered = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter, (user, operation_id) in operations.items():
                    claimed = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "retry", operation_id),
                        "领取悬赏",
                    )
                    assert claimed.code == "BOUNTY_CLAIMED"
                    assert claimed.data["rewards"] == {
                        "spirit_stones": 31,
                        "local_reputation": 5,
                    }
                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "replay", operation_id),
                        "领取悬赏",
                    )
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["rewards"] == claimed.data["rewards"]
                    _, _, status, reputation_json = _player_state(recovered, adapter, user)
                    assert status == "claimed"
                    assert json.loads(reputation_json)["local.xuantian.new_town"] == 1000
            finally:
                await recovered.close()

    asyncio.run(run())


def test_bounty_claim_freezes_equipment_and_codex_projection_after_content_change() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_gear_and_codex_reward(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-codex-{adapter}"
                    await _create_mortal(runtime, adapter, user)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', "
                            "realm_layer=1, path_key='body' WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        )
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", f"{adapter}:bounty-codex-accept"),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)
                await runtime.close()

                equipment_path = data_dir / "装备" / "法器.json"
                equipment_document = _json(equipment_path)
                equipment = next(
                    row for row in equipment_document["records"]
                    if row["key"] == "item.weapon.body.pulse_edge"
                )
                equipment["name"] = "改名后的法器"
                equipment["status"] = "locked"
                _write_json(equipment_path, equipment_document)
                codex_path = data_dir / "图鉴" / "条目.json"
                codex_document = _json(codex_path)
                codex = next(
                    row for row in codex_document["records"]
                    if row["key"] == "codex.story.beast_habitat"
                )
                codex["name"] = "改名后的见闻"
                codex["status"] = "locked"
                _write_json(codex_path, codex_document)

                recovered = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
                try:
                    for adapter in _ADAPTERS:
                        user = f"bounty-codex-{adapter}"
                        claim = await recovered.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "claim", f"{adapter}:bounty-codex-claim"),
                            "领取悬赏",
                        )
                        assert claim.code == "BOUNTY_CLAIMED"
                        assert claim.data["rewards"] == {
                            "item.weapon.body.pulse_edge": 1,
                            "codex.story.beast_habitat": 1,
                        }
                        assert "拓脉短锋 +1" in claim.message
                        with sqlite3.connect(recovered.settings.database_path) as connection:
                            player_id = connection.execute(
                                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()[0]
                            equipment_row = connection.execute(
                                "SELECT item_key, label, slot FROM equipment_instances "
                                "WHERE player_id=? AND item_key=?",
                                (player_id, "item.weapon.body.pulse_edge"),
                            ).fetchone()
                            codex_row = connection.execute(
                                "SELECT category FROM codex_entries WHERE player_id=? AND entry_key=?",
                                (player_id, "codex.story.beast_habitat"),
                            ).fetchone()
                            inventory = json.loads(
                                connection.execute(
                                    "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                                ).fetchone()[0]
                            )
                        assert equipment_row == (
                            "item.weapon.body.pulse_edge", "拓脉短锋", "weapon"
                        )
                        assert codex_row == ("story",)
                        assert "item.weapon.body.pulse_edge" not in inventory
                finally:
                    await recovered.close()
            finally:
                await runtime.close()

    asyncio.run(run())


def test_bounty_daily_limit_comes_from_content_and_allows_multiple_distinct_claims() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_fixed_herb_reward(data_dir)
            bounty_path = data_dir / "任务" / "悬赏.json"
            bounties = _json(bounty_path)
            herb = next(row for row in bounties["records"] if row["key"] == "bounty.herb_supply")
            herb["daily_limit"] = 2
            _write_json(bounty_path, bounties)

            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-daily-limit-{adapter}"
                    await _create_mortal(runtime, adapter, user)
                    first = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "first", f"{adapter}:bounty-first"),
                        "接取悬赏 草药补给",
                    )
                    assert first.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "first-claim", f"{adapter}:bounty-first-claim"),
                        "领取悬赏",
                    )
                    assert claimed.code == "BOUNTY_CLAIMED"

                    second = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "second", f"{adapter}:bounty-second"),
                        "接取悬赏 草药补给",
                    )
                    assert second.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)
                    second_claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "second-claim", f"{adapter}:bounty-second-claim"),
                        "领取悬赏",
                    )
                    assert second_claim.code == "BOUNTY_CLAIMED"

                    third = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "third", f"{adapter}:bounty-third"),
                        "接取悬赏 草药补给",
                    )
                    assert third.code == "BOUNTY_DAILY_LIMIT"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_random_bounty_freezes_choice_evidence_and_previews_selected_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-random-{adapter}"
                    await _create_mortal(runtime, adapter, user)
                    board = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "board"), "悬赏榜"
                    )
                    available = {
                        row["bounty_key"] for row in board.data["offers"]
                        if row["status"] == "available"
                    }
                    operation_id = f"{adapter}:bounty-random-accept"
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "random", operation_id),
                        "接取悬赏",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "random-replay", operation_id),
                        "接取悬赏",
                    )
                    assert replay.data["idempotent_replay"] is True
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot_json = connection.execute(
                            "SELECT snapshot_json FROM bounty_offers WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0]
                    snapshot = json.loads(snapshot_json)
                    selection = snapshot["selection"]
                    assert isinstance(selection["bounty_choice_seed"], str)
                    assert selection["bounty_choice_seed"] != operation_id
                    assert selection["reward_seed"] != selection["bounty_choice_seed"]
                    assert selection["reward_seed"] != operation_id
                    assert {
                        row["bounty_key"] for row in selection["candidate_weights"]
                    } == available
                    chosen_preview = next(
                        row for row in board.data["offers"]
                        if row["bounty_key"] == accepted.data["bounty_key"]
                    )
                    assert chosen_preview["status"] == "available"
                    assert isinstance(chosen_preview["reward"], dict)
            finally:
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "invalid_field",
    (
        "consume_target",
        "reward_quantity",
        "inactive_reward_item",
        "empty_reward",
        "enemy_target",
        "dispatch_target",
    ),
)
def test_bounty_content_rejects_invalid_delivery_and_reward_types(
    tmp_path: Path, invalid_field: str
) -> None:
    data_dir = tmp_path / invalid_field
    _copy_content(data_dir)
    if invalid_field == "consume_target":
        path = data_dir / "任务" / "悬赏.json"
        document = _json(path)
        herb = next(row for row in document["records"] if row["key"] == "bounty.herb_supply")
        herb["consume_target"] = "false"
    elif invalid_field in {
        "reward_quantity",
        "empty_reward",
        "inactive_reward_item",
    }:
        path = data_dir / "奖励" / "奖励.json"
        document = _json(path)
        pool = next(
            row for row in document["records"]
            if row["key"] == "reward_pool.bounty.herb_supply"
        )
        if invalid_field == "reward_quantity":
            pool["outcomes"][0]["rewards"]["local_reputation"] = True
        else:
            pool["outcomes"] = [{"weight": 1, "no_reward": True}]
        if invalid_field == "inactive_reward_item":
            pool["outcomes"] = [
                {"weight": 1, "rewards": {"item.herb.blood_grass": 1}}
            ]
            item_path = data_dir / "道具" / "材料.json"
            items = _json(item_path)
            item = next(
                row for row in items["records"]
                if row["key"] == "item.herb.blood_grass"
            )
            item["status"] = "locked"
            _write_json(item_path, items)
        elif invalid_field == "reward_quantity":
            pool["outcomes"][0]["rewards"]["local_reputation"] = True
        else:
            pool["outcomes"] = [{"weight": 1, "no_reward": True}]
    elif invalid_field in {"enemy_target", "dispatch_target"}:
        path = data_dir / "任务" / "悬赏.json"
        document = _json(path)
        bounty_key = "bounty.elite_hunt" if invalid_field == "enemy_target" else "bounty.beast_habitat"
        bounty = next(row for row in document["records"] if row["key"] == bounty_key)
        bounty["target_key"] = (
            "enemy.missing" if invalid_field == "enemy_target" else "dispatch.missing"
        )
    else:
        raise AssertionError(invalid_field)
    _write_json(path, document)

    with pytest.raises(ContentError):
        bounty_definitions(ContentBundle.load(data_dir))
