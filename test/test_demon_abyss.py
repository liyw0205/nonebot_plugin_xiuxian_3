from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon
from travel_fixtures import set_travel_end_at

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map


DEMON_REWARD_POOL = "reward_pool.exploration.demon_abyss"
CONTENT = ContentBundle.load(Path(__file__).parents[1] / "data")


def _demon_reward(operation_id: str) -> dict[str, int]:
    return reward_pool_map(
        DEMON_REWARD_POOL,
        f"{operation_id}:reward",
        CONTENT,
    )


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _player(runtime, adapter: str, user: str, *, strong: bool, pollution: int = 0) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='demon.abyss_gate', path_key='spell', stamina=60, stamina_max=60,
                energy=30, energy_max=30, soul_power=100, soul_power_max=100,
                pollution=?, max_hp=?, initiative=?, qualification_json=?, faction_reputation_json='{}',
                intro_json='{"flags":["access.demon_abyss_gate"]}'
            WHERE platform=? AND platform_user_id=?
            """,
            (
                pollution,
                100000 if strong else 0,
                100000 if strong else 0,
                json.dumps(
                    BALANCED_QUALIFICATION if strong else {
                        "body": 5, "spirit": 15, "insight": 15,
                        "root": 5, "agility": 5, "fortune": 15,
                    },
                    sort_keys=True,
                ),
                adapter,
                user,
            ),
        )
    if strong:
        equip_damage_weapon(runtime, adapter, user, 50000)


def _expire(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def _expire_travel(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        set_travel_end_at(
            connection,
            session_id,
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )


def test_demon_abyss_success_and_replay_on_qq_and_onebot() -> None:
    async def run() -> None:
        operation = next(
            f"demon-success-{index}"
            for index in range(1000)
            if _demon_reward(f"demon-success-{index}") == {"item.demon_core": 1}
        )
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"demon-success-{adapter}"
                await _player(runtime, adapter, user, strong=True)
                travel = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "travel-start"),
                    "前往 魔界堕落遗迹",
                )
                assert travel.code == "TRAVEL_STARTED"
                _expire_travel(runtime, travel.data["session_id"])
                arrived = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "travel-settle"),
                    "结算移动",
                )
                assert arrived.code == "TRAVEL_COMPLETED"

                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "explore-start", operation),
                    "开始探索 魔界堕落遗迹探索",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["pollution_before"] == 0
                assert started.data["pollution_after"] == 10
                assert started.data["cross_realm_penalty_bp"] == 1000
                _expire(runtime, started.data["exploration_id"])
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "explore-settle", "demon-settle"),
                    "结算探索",
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == {"item.demon_core": 1}
                assert settled.data["pollution_after"] == 10
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "explore-replay", "demon-settle"),
                    "结算探索",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory_text, pollution = connection.execute(
                        "SELECT inventory_json, pollution FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory_text)["item.demon_core"] == 1
                assert pollution == 10
                await runtime.close()

    asyncio.run(run())


def test_demon_abyss_contract_clue_is_frozen_and_idempotent_on_both_adapters() -> None:
    async def run() -> None:
        operation = next(
            f"demon-contract-{index}"
            for index in range(1000)
            if _demon_reward(f"demon-contract-{index}") == {"item.clue.demon_contract": 1}
        )
        assert ContentBundle.load(Path(__file__).parents[1] / "data").require(
            "item", "item.clue.demon_contract"
        )["bind_type"] == "character_bound"
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"demon-contract-{adapter}"
                await _player(runtime, adapter, user, strong=True)
                travel = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contract-travel-start"),
                    "前往 魔界堕落遗迹",
                )
                assert travel.code == "TRAVEL_STARTED"
                _expire_travel(runtime, travel.data["session_id"])
                arrived = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contract-travel-settle"),
                    "结算移动",
                )
                assert arrived.code == "TRAVEL_COMPLETED"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contract-explore-start", operation),
                    "开始探索 魔界堕落遗迹探索",
                )
                assert started.code == "EXPLORATION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (started.data["exploration_id"],),
                    ).fetchone()[0]
                snapshot = json.loads(snapshot)
                assert snapshot["random_pool"] == "loot.demon.abyss"
                assert snapshot["reward_pool_key"] == DEMON_REWARD_POOL
                assert snapshot["frozen_result"] == {"item.clue.demon_contract": 1}
                _expire(runtime, started.data["exploration_id"])
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contract-explore-settle", "demon-contract-settle"),
                    "结算探索",
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == {"item.clue.demon_contract": 1}
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "contract-explore-replay", "demon-contract-settle"),
                    "结算探索",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory = connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                assert json.loads(inventory)["item.clue.demon_contract"] == 1
                await runtime.close()

    asyncio.run(run())


def test_demon_abyss_reputation_reward_is_snapshotted_and_projected() -> None:
    async def run() -> None:
        operation = next(
            f"demon-reputation-{index}"
            for index in range(1000)
            if _demon_reward(f"demon-reputation-{index}") == {"faction_reputation.demon": 15}
        )
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter, user = "qq.official", "demon-reputation"
            await _player(runtime, adapter, user, strong=True)
            travel = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "reputation-travel-start"),
                "前往 魔界堕落遗迹",
            )
            assert travel.code == "TRAVEL_STARTED"
            _expire_travel(runtime, travel.data["session_id"])
            arrived = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "reputation-travel-settle"),
                "结算移动",
            )
            assert arrived.code == "TRAVEL_COMPLETED"

            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "reputation-explore-start", operation),
                "开始探索 魔界堕落遗迹探索",
            )
            assert started.code == "EXPLORATION_STARTED"
            _expire(runtime, started.data["exploration_id"])
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "reputation-explore-settle", "demon-reputation-settle"),
                "结算探索",
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == "won"
            assert settled.data["result"] == {"faction_reputation.demon": 15}

            with sqlite3.connect(runtime.settings.database_path) as connection:
                faction_text, battle_id, snapshot_text = connection.execute(
                    """
                    SELECT p.faction_reputation_json, b.battle_id, b.snapshot_json
                    FROM players p
                    JOIN battle_sessions b ON b.player_id = p.id
                    WHERE p.platform=? AND p.platform_user_id=?
                    ORDER BY b.id DESC LIMIT 1
                    """,
                    (adapter, user),
                ).fetchone()
            assert json.loads(faction_text)["demon"] == 15
            assert battle_id == settled.data["battle_id"]
            assert json.loads(snapshot_text)["player"]["cross_realm_penalty_bp"] == 1000

            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "reputation-explore-replay", "demon-reputation-settle"),
                "结算探索",
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                faction_text = connection.execute(
                    "SELECT faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
            assert json.loads(faction_text)["demon"] == 15
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_demon_abyss_failure_sets_soul_fatigue_and_guards_pollution(
    adapter: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The encounter seed includes this UUID; keep the real defeat reproducible.
    exploration_uuid = UUID(int=0)
    monkeypatch.setattr(
        "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.uuid4",
        lambda: exploration_uuid,
    )

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "demon-failure"
            await _player(runtime, adapter, user, strong=False)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='demon.fallen_ruins' WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
                assets_before = connection.execute(
                    "SELECT inventory_json, spirit_stones, cultivation, total_cultivation, "
                    "faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "failure-start", "demon-failure-start"),
                "开始探索 魔界堕落遗迹探索",
            )
            assert started.code == "EXPLORATION_STARTED"
            assert started.data["exploration_id"] == exploration_uuid.hex
            _expire(runtime, started.data["exploration_id"])
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "failure-settle", "demon-failure-settle"),
                "结算探索",
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == "lost"
            assert settled.data["result"] == {}
            assert settled.data["soul_power_loss"] == 20
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "failure-replay", "demon-failure-settle"),
                "结算探索",
            )
            assert replay.code == "EXPLORATION_SETTLED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["battle_id"] == settled.data["battle_id"]
            assert replay.data["battle_outcome"] == "lost"
            assert replay.data["result"] == {}
            assert replay.data["soul_power_loss"] == 20
            with sqlite3.connect(runtime.settings.database_path) as connection:
                soul_power, fatigue, pollution, stamina = connection.execute(
                    "SELECT soul_power, soul_fatigue_until, pollution, stamina "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assets_after = connection.execute(
                    "SELECT inventory_json, spirit_stones, cultivation, total_cultivation, "
                    "faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                status, reward_status, state_text, snapshot_text = connection.execute(
                    "SELECT status, reward_status, state_json, snapshot_json FROM battle_sessions "
                    "WHERE battle_id=?",
                    (settled.data["battle_id"],),
                ).fetchone()
                assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 1
            assert soul_power == 80
            assert fatigue
            assert pollution == 10
            assert stamina == 60 - started.data["stamina_cost"]
            assert assets_after == assets_before
            assert status == "settled"
            assert reward_status == "none"
            assert json.loads(state_text)["player_hp"] == 0
            assert json.loads(snapshot_text)["random_seed"] == f"exploration.battle:{exploration_uuid.hex}"
            blocked = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "fatigue-block"),
                "开始探索 魔界堕落遗迹探索",
            )
            assert blocked.code == "SOUL_EXHAUSTION_ACTIVE"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET soul_fatigue_until=NULL, pollution=80 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            pollution_blocked = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "pollution-block"),
                "开始探索 魔界堕落遗迹探索",
            )
            assert pollution_blocked.code == "POLLUTION_TOO_HIGH"
            await runtime.close()

    asyncio.run(run())
