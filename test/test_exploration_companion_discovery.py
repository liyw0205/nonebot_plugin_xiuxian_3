from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import companion_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    exploration_discovery_weight_bp,
    settlement_result,
)


def _context(adapter: str, user_id: str, operation_id: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user_id,
        operation_id=operation_id,
    )


def _record(document: dict[str, object], key: str) -> dict[str, object]:
    records = document["records"]
    assert isinstance(records, list)
    return next(row for row in records if isinstance(row, dict) and row.get("key") == key)


def test_exploration_discovery_weights_freeze_for_both_adapters_and_replay_after_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            source_data = Path(__file__).parents[1] / "data"
            shutil.copytree(source_data, data_dir)

            companion_path = data_dir / "灵兽" / "灵兽.json"
            companions = json.loads(companion_path.read_text(encoding="utf-8"))
            wood_rat = _record(companions, "beast.wood_rat")
            assert isinstance(wood_rat.get("effect"), dict)
            wood_rat["effect"]["value"] = 5_000
            companion_path.write_text(
                json.dumps(companions, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            reward_path = data_dir / "奖励" / "奖励.json"
            rewards = json.loads(reward_path.read_text(encoding="utf-8"))
            pool = _record(rewards, "reward_pool.exploration.beast_hunt")
            pool["outcomes"] = [
                {"weight": 1, "rewards": {"item.beast_blood": 1}},
                {"weight": 1, "rewards": {"faction_reputation.beast": 15}},
            ]
            reward_path.write_text(
                json.dumps(rewards, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            adapters = ("qq.official", "onebot.v11")
            runtime = create_runtime(data_dir=data_dir, adapters=adapters)
            operations: dict[str, str] = {}
            settlement_operations: dict[str, str] = {}
            expected_results: dict[str, dict[str, int]] = {}
            try:
                for adapter in adapters:
                    user_id = f"discovery-{adapter}"
                    created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user_id, f"{adapter}:create"),
                        "开始修仙",
                    )
                    assert created.code == "PLAYER_CREATED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET location_key='xuantian.outskirts', inventory_json='{}' "
                            "WHERE platform=? AND platform_user_id=?",
                            (adapter, user_id),
                        )

                    has_companion = adapter == "qq.official"
                    if has_companion:
                        bonded = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user_id, f"{adapter}:bond"),
                            "结缘灵兽 beast.wood_rat",
                        )
                        assert bonded.code == "COMPANION_BONDED"

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', "
                            "realm_layer=1, path_key='beast', location_key='beast.ten_thousand_hills', "
                            "stamina=30, max_hp=999, initiative=99, qualification_json=? "
                            "WHERE platform=? AND platform_user_id=?",
                            (json.dumps(BALANCED_QUALIFICATION), adapter, user_id),
                        )
                    equip_damage_weapon(runtime, adapter, user_id, damage=50_000)

                    bonus = 5_000 if has_companion else 0
                    operation_id = (
                        next(
                            f"{adapter}:discovery:{index}"
                            for index in range(10_000)
                            if settlement_result(
                                "explore.beast_hunt",
                                f"{adapter}:discovery:{index}",
                                content=runtime.content,
                            )
                            != settlement_result(
                                "explore.beast_hunt",
                                f"{adapter}:discovery:{index}",
                                drop_weight_bp=bonus,
                                content=runtime.content,
                            )
                        )
                        if has_companion
                        else f"{adapter}:discovery:baseline"
                    )
                    operations[adapter] = operation_id
                    expected = settlement_result(
                        "explore.beast_hunt",
                        operation_id,
                        drop_weight_bp=bonus,
                        content=runtime.content,
                    )
                    expected_results[adapter] = expected

                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user_id, operation_id),
                        "开始探索 万兽山狩猎",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        stored = connection.execute(
                            "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                            (started.data["exploration_id"],),
                        ).fetchone()
                        stamina = connection.execute(
                            "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user_id),
                        ).fetchone()[0]
                    snapshot = json.loads(stored[0])
                    assert snapshot["exploration_discovery_bp"] == bonus
                    assert snapshot["frozen_result"] == expected
                    assert stamina == 10

                    repeated = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user_id, operation_id),
                        "开始探索 万兽山狩猎",
                    )
                    assert repeated.data["exploration_id"] == started.data["exploration_id"]
                    assert repeated.data["idempotent_replay"] is True

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                            (
                                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                                started.data["exploration_id"],
                            ),
                        )
                    settle_operation = f"{adapter}:discovery:settle"
                    settlement_operations[adapter] = settle_operation
                    settled = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user_id, settle_operation),
                        "结算探索",
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["battle_outcome"] == "won"
                    assert settled.data["result"] == expected
                    repeated_settlement = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user_id, settle_operation),
                        "结算探索",
                    )
                    assert repeated_settlement.data["idempotent_replay"] is True
                    assert repeated_settlement.data["result"] == expected
            finally:
                await runtime.close()

            recovered = create_runtime(data_dir=data_dir, adapters=adapters)
            try:
                for adapter in adapters:
                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, f"discovery-{adapter}", settlement_operations[adapter]),
                        "结算探索",
                    )
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["result"] == expected_results[adapter]
            finally:
                await recovered.close()

    asyncio.run(run())


def test_exploration_discovery_weight_combines_sources_and_obeys_cap() -> None:
    companion = {
        "effect": {"type": "exploration_discovery_bp", "value": 4_800, "cap": 10_000}
    }
    assert exploration_discovery_weight_bp(
        {"type": "drop_weight_bp", "value": 400}, [companion]
    ) == 5_000
    assert exploration_discovery_weight_bp({}, [companion]) == 4_800


def test_companion_discovery_content_rejects_boolean_weight(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    companion_path = data_dir / "灵兽" / "灵兽.json"
    document = json.loads(companion_path.read_text(encoding="utf-8"))
    record = _record(document, "beast.wood_rat")
    assert isinstance(record.get("effect"), dict)
    record["effect"]["value"] = True
    companion_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="探索发现效果"):
        companion_definition("beast.wood_rat", ContentBundle.load(data_dir))
