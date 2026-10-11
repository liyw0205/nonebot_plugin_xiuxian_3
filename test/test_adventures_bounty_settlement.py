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


def _configure_claim_integrity_reward(data_dir: Path, *, consume_target: bool) -> None:
    reward_path = data_dir / "奖励" / "奖励.json"
    rewards = _json(reward_path)
    pool = next(
        row for row in rewards["records"]
        if row["key"] == "reward_pool.bounty.herb_supply"
    )
    pool["outcomes"] = [
        {
            "weight": 1,
            "rewards": {
                "spirit_stones": 31,
                "local_reputation": 10,
                "item.weapon.body.pulse_edge": 1,
                "codex.story.beast_habitat": 1,
            },
        }
    ]
    _write_json(reward_path, rewards)

    bounty_path = data_dir / "任务" / "悬赏.json"
    bounties = _json(bounty_path)
    herb = next(
        row for row in bounties["records"] if row["key"] == "bounty.herb_supply"
    )
    herb["consume_target"] = consume_target
    _write_json(bounty_path, bounties)


def _duplicate_json_member(raw: str, parent_key: str, key: str, value: object) -> str:
    parent_marker = f'"{parent_key}"'
    parent_index = raw.index(parent_marker)
    object_start = raw.index("{", parent_index + len(parent_marker))
    object_end = raw.index("}", object_start)
    duplicate = f", {json.dumps(key)}: {json.dumps(value)}"
    return raw[:object_end] + duplicate + raw[object_end:]


def _bounty_claim_integrity_state(
    runtime, adapter: str, user: str, accept_operation_id: str, claim_operation_id: str
) -> tuple[object, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT id, spirit_stones, inventory_json FROM players "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        player_id = player[0]
        reputation = connection.execute(
            "SELECT local_json, service_reputation FROM player_reputations WHERE player_id=?",
            (player_id,),
        ).fetchone()
        offer = connection.execute(
            "SELECT status, result_json FROM bounty_offers WHERE operation_id=?",
            (accept_operation_id,),
        ).fetchone()
        equipment_count = connection.execute(
            "SELECT COUNT(*) FROM equipment_instances WHERE player_id=? AND item_key=?",
            (player_id, "item.weapon.body.pulse_edge"),
        ).fetchone()[0]
        codex_count = connection.execute(
            "SELECT COUNT(*) FROM codex_entries WHERE player_id=? AND entry_key=?",
            (player_id, "codex.story.beast_habitat"),
        ).fetchone()[0]
        operation = connection.execute(
            "SELECT player_id, request_hash, result_json FROM operations WHERE operation_id=?",
            (claim_operation_id,),
        ).fetchone()
    return (
        tuple(player),
        tuple(reputation) if reputation is not None else None,
        tuple(offer) if offer is not None else None,
        equipment_count,
        codex_count,
        tuple(operation) if operation is not None else None,
    )


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


def test_bounty_claim_rejects_duplicate_reward_snapshot_before_all_writes_then_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_claim_integrity_reward(data_dir, consume_target=True)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            offer_operations: dict[str, str] = {}
            claim_operations: dict[str, str] = {}
            accepted_snapshots: dict[str, str] = {}
            before_states: dict[str, tuple[object, ...]] = {}
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-duplicate-snapshot-{adapter}"
                    offer_operation = f"{adapter}:duplicate-snapshot-accept"
                    claim_operation = f"{adapter}:duplicate-snapshot-claim"
                    offer_operations[adapter] = offer_operation
                    claim_operations[adapter] = claim_operation
                    await _create_mortal(runtime, adapter, user)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', "
                            "realm_layer=1, path_key='body' "
                            "WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        )
                    _set_local_reputation(
                        runtime, adapter, user, '{"local.xuantian.new_town":995}'
                    )
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", offer_operation),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        accepted_snapshots[adapter] = connection.execute(
                            "SELECT snapshot_json FROM bounty_offers WHERE operation_id=?",
                            (offer_operation,),
                        ).fetchone()[0]
                    corrupted_snapshot = _duplicate_json_member(
                        accepted_snapshots[adapter], "reward", "spirit_stones", 999
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET snapshot_json=? WHERE operation_id=?",
                            (corrupted_snapshot, offer_operation),
                        )
                    before_states[adapter] = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )

                    rejected = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "duplicate-snapshot", claim_operation),
                        "领取悬赏",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_states[adapter]
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT snapshot_json FROM bounty_offers WHERE operation_id=?",
                            (offer_operation,),
                        ).fetchone()[0] == corrupted_snapshot
                await runtime.close()

                recovered = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
                try:
                    for adapter in _ADAPTERS:
                        user = f"bounty-duplicate-snapshot-{adapter}"
                        offer_operation = offer_operations[adapter]
                        claim_operation = claim_operations[adapter]
                        with sqlite3.connect(recovered.settings.database_path) as connection:
                            connection.execute(
                                "UPDATE bounty_offers SET snapshot_json=? WHERE operation_id=?",
                                (accepted_snapshots[adapter], offer_operation),
                            )

                        claimed = await recovered.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "retry", claim_operation),
                            "领取悬赏",
                        )
                        assert claimed.code == "BOUNTY_CLAIMED"
                        assert claimed.data["rewards"] == {
                            "spirit_stones": 31,
                            "local_reputation": 5,
                            "item.weapon.body.pulse_edge": 1,
                            "codex.story.beast_habitat": 1,
                        }
                        state_after_claim = _bounty_claim_integrity_state(
                            recovered, adapter, user, offer_operation, claim_operation
                        )
                        assert state_after_claim[2][0] == "claimed"
                        assert state_after_claim[3:5] == (1, 1)
                        assert state_after_claim[5] is not None
                        assert json.loads(state_after_claim[1][0]) == {
                            "local.xuantian.new_town": 1000
                        }

                        inventory_before = json.loads(before_states[adapter][0][2])
                        inventory_after = json.loads(state_after_claim[0][2])
                        inventory_before["item.herb.blood_grass"] -= 5
                        if inventory_before["item.herb.blood_grass"] == 0:
                            del inventory_before["item.herb.blood_grass"]
                        assert inventory_after == inventory_before
                        assert state_after_claim[0][1] == before_states[adapter][0][1] + 31

                        replay = await recovered.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "replay", claim_operation),
                            "领取悬赏",
                        )
                        assert replay.code == "BOUNTY_CLAIMED", replay.message
                        assert replay.data["idempotent_replay"] is True
                        assert replay.data["rewards"] == claimed.data["rewards"]
                        assert _bounty_claim_integrity_state(
                            recovered, adapter, user, offer_operation, claim_operation
                        ) == state_after_claim
                finally:
                    await recovered.close()
            finally:
                await runtime.close()

    asyncio.run(run())


def test_bounty_claim_replay_rejects_damaged_offer_and_operation_results_read_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            _configure_fixed_herb_reward(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            claim_operations: dict[str, str] = {}
            canonical_states: dict[str, tuple[object, ...]] = {}
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-claim-replay-integrity-{adapter}"
                    offer_operation = f"{adapter}:claim-integrity-accept"
                    claim_operation = f"{adapter}:claim-integrity-claim"
                    claim_operations[adapter] = claim_operation
                    await _create_mortal(runtime, adapter, user)
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", offer_operation),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    _add_herbs(runtime, adapter, user)
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "claim", claim_operation),
                        "领取悬赏",
                    )
                    assert claimed.code == "BOUNTY_CLAIMED"
                    canonical_states[adapter] = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    canonical_offer_result = canonical_states[adapter][2][1]
                    canonical_operation_result = canonical_states[adapter][5][2]

                    offer_payload = json.loads(canonical_offer_result)
                    offer_payload["rewards"]["spirit_stones"] = 999
                    damaged_offer_result = json.dumps(
                        offer_payload, ensure_ascii=False, sort_keys=True
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (damaged_offer_result, offer_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    offer_result_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "bad-offer-result", claim_operation),
                        "领取悬赏",
                    )
                    assert offer_result_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (canonical_offer_result, offer_operation),
                        )

                    excessive_offer_progress = json.loads(canonical_offer_result)
                    excessive_offer_progress["progress"] = (
                        excessive_offer_progress["target"] + 1
                    )
                    excessive_offer_result = json.dumps(
                        excessive_offer_progress, ensure_ascii=False, sort_keys=True
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (excessive_offer_result, offer_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    excessive_offer_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "excessive-offer-progress", claim_operation),
                        "领取悬赏",
                    )
                    assert excessive_offer_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (canonical_offer_result, offer_operation),
                        )

                    damaged_operation_result = _duplicate_json_member(
                        canonical_operation_result, "rewards", "spirit_stones", 999
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (damaged_operation_result, claim_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    duplicate_operation_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "duplicate-operation-result", claim_operation),
                        "领取悬赏",
                    )
                    assert duplicate_operation_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay

                    excessive_operation_progress = json.loads(canonical_operation_result)
                    excessive_operation_progress["progress"] = (
                        excessive_operation_progress["target"] + 1
                    )
                    excessive_operation_result = json.dumps(
                        excessive_operation_progress, ensure_ascii=False, sort_keys=True
                    )
                    excessive_offer_progress = json.loads(canonical_offer_result)
                    excessive_offer_progress["progress"] = (
                        excessive_offer_progress["target"] + 1
                    )
                    excessive_offer_result = json.dumps(
                        excessive_offer_progress, ensure_ascii=False, sort_keys=True
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (excessive_operation_result, claim_operation),
                        )
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (excessive_offer_result, offer_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    excessive_progress_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "excessive-progress-results", claim_operation),
                        "领取悬赏",
                    )
                    assert excessive_progress_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (canonical_operation_result, claim_operation),
                        )
                        connection.execute(
                            "UPDATE bounty_offers SET result_json=? WHERE operation_id=?",
                            (canonical_offer_result, offer_operation),
                        )

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            ("{malformed", claim_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    malformed_operation_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "malformed-operation-result", claim_operation),
                        "领取悬赏",
                    )
                    assert malformed_operation_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay

                    mismatched_identity = json.loads(canonical_operation_result)
                    mismatched_identity["player"]["id"] = "foreign-player"
                    mismatched_identity["player"]["player_id"] = "foreign-player"
                    mismatched_identity["player"]["platform_user_id"] = "foreign-user"
                    damaged_identity_result = json.dumps(
                        mismatched_identity, ensure_ascii=False, sort_keys=True
                    )
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (damaged_identity_result, claim_operation),
                        )
                    before_rejected_replay = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    identity_mismatch_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "identity-mismatch-result", claim_operation),
                        "领取悬赏",
                    )
                    assert identity_mismatch_replay.code == "PERSISTENCE_ERROR"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == before_rejected_replay

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (canonical_operation_result, claim_operation),
                        )
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "repaired-replay", claim_operation),
                        "领取悬赏",
                    )
                    assert replay.code == "BOUNTY_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == canonical_states[adapter]
            finally:
                await runtime.close()

    asyncio.run(run())


def test_expired_bounty_claim_replays_without_reapplying_state_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            _copy_content(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            try:
                for adapter in _ADAPTERS:
                    user = f"bounty-expired-replay-{adapter}"
                    offer_operation = f"{adapter}:expired-accept"
                    claim_operation = f"{adapter}:expired-claim"
                    await _create_mortal(runtime, adapter, user)
                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", offer_operation),
                        "接取悬赏 草药补给",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE bounty_offers SET expires_at='2000-01-01T00:00:00+00:00' "
                            "WHERE operation_id=?",
                            (offer_operation,),
                        )
                    before = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )

                    expired = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "expire", claim_operation),
                        "领取悬赏",
                    )
                    assert expired.code == "BOUNTY_EXPIRED"
                    after_expiry = _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    )
                    assert after_expiry[0] == before[0]
                    assert after_expiry[3:5] == before[3:5]
                    assert after_expiry[2][0] == "expired"
                    assert after_expiry[5] is not None

                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "expired-replay", claim_operation),
                        "领取悬赏",
                    )
                    assert replay.code == "BOUNTY_EXPIRED"
                    assert _bounty_claim_integrity_state(
                        runtime, adapter, user, offer_operation, claim_operation
                    ) == after_expiry
            finally:
                await runtime.close()

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
                    assert "[接取](command:" in board.message
                    available = {
                        row["bounty_key"] for row in board.data["offers"]
                        if row["status"] == "available"
                    }
                    assert board.data["refresh_seed"].startswith("bounty-refresh:")
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
                    assert selection["refresh_seed"] == board.data["refresh_seed"]
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
    "condition",
    (
        {"type": "unknown", "value": "x"},
        {"type": "inventory_item", "item_key": "", "quantity": 1},
        {"type": "inventory_item", "item_key": "item.herb.blood_grass", "quantity": True},
        {"type": "permit", "permit_key": "permit.cloud_mine", "unused": True},
        {"type": [], "value": "x"},
    ),
    ids=("unknown", "empty-item-key", "invalid-quantity", "unused-field", "invalid-type"),
)
def test_bounty_content_rejects_invalid_access_any_contract(
    tmp_path: Path, condition: dict[str, object]
) -> None:
    data_dir = tmp_path / "content"
    _copy_content(data_dir)
    path = data_dir / "任务" / "悬赏.json"
    document = _json(path)
    bounty = next(
        row for row in document["records"] if row["key"] == "bounty.cloud_mine"
    )
    bounty["access_any"] = [condition]
    _write_json(path, document)

    with pytest.raises(ContentError):
        bounty_definitions(ContentBundle.load(data_dir))


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
