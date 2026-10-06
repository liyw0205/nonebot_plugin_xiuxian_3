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


_ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, request: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"{user}:{request}",
        operation_id=operation_id,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record(document: dict[str, object], key: str) -> dict[str, object]:
    records = document["records"]
    assert isinstance(records, list)
    return next(row for row in records if isinstance(row, dict) and row.get("key") == key)


def _set_player(runtime, adapter: str, user: str, path_key: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
            "path_key=?, location_key='xuantian.outskirts', stamina=100, max_hp=999, initiative=99, "
            "qualification_json=? WHERE platform=? AND platform_user_id=?",
            (path_key, json.dumps({"body": 2_000, "agility": 2_000}), adapter, user),
        )


def _player_assets(runtime, adapter: str, user: str) -> tuple[int, int, dict[str, int]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT spirit_stones, cultivation, inventory_json FROM players "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
    return int(row[0]), int(row[1]), json.loads(row[2])


def _configure_initial_body_reward(data_dir: Path) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = _read_json(path)
    pool = _record(document, "reward_pool.bounty.body_trial")
    pool.pop("equipment_reward_qualities", None)
    pool["outcomes"] = [
        {
            "weight": 1,
            "rewards": {
                "cultivation": 180,
                "spirit_stones": 25,
                "item.pill.healing_low": 1,
            },
        }
    ]
    _write_json(path, document)


def _change_body_bounty_after_acceptance(data_dir: Path) -> None:
    bounty_path = data_dir / "任务" / "悬赏.json"
    bounties = _read_json(bounty_path)
    body_trial = _record(bounties, "bounty.body_trial")
    body_trial["target_amount"] = 3
    body_trial["reward_pool_key"] = "reward_pool.bounty.craft_order"
    _write_json(bounty_path, bounties)

    reward_path = data_dir / "奖励" / "奖励.json"
    rewards = _read_json(reward_path)
    pool = _record(rewards, "reward_pool.bounty.body_trial")
    pool["outcomes"] = [{"weight": 1, "rewards": {"cultivation": 999}}]
    _write_json(reward_path, rewards)


def test_body_trial_uses_real_exploration_wins_and_frozen_bounty_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _configure_initial_body_reward(data_dir)
            runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
            accept_operations: dict[str, str] = {}
            claim_operations: dict[str, str] = {}
            claim_balances: dict[str, tuple[int, int, dict[str, int]]] = {}
            try:
                for adapter in _ADAPTERS:
                    user = f"body-trial-{adapter}"
                    accept_operation = f"{adapter}:body-trial:accept"
                    claim_operation = f"{adapter}:body-trial:claim"
                    accept_operations[adapter] = accept_operation
                    claim_operations[adapter] = claim_operation
                    created = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                    assert created.code == "PLAYER_CREATED"
                    _set_player(runtime, adapter, user, "body")

                    accepted = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept", accept_operation),
                        "接取悬赏 淬体试炼",
                    )
                    assert accepted.code == "BOUNTY_ACCEPTED"
                    assert accepted.data["bounty_key"] == "bounty.body_trial"
                    assert accepted.data["target"] == 2
                    repeated_accept = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept-replay", accept_operation),
                        "接取悬赏 淬体试炼",
                    )
                    assert repeated_accept.data["idempotent_replay"] is True

                    wrong_path_user = f"body-trial-wrong-path-{adapter}"
                    wrong_path_created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, wrong_path_user, "create"),
                        "开始修仙",
                    )
                    assert wrong_path_created.code == "PLAYER_CREATED"
                    _set_player(runtime, adapter, wrong_path_user, "spell")
                    denied = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, wrong_path_user, "wrong-path"),
                        "接取悬赏 淬体试炼",
                    )
                    assert denied.code == "BOUNTY_REQUIREMENT_MISSING"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM bounty_offers WHERE player_id="
                            "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, wrong_path_user),
                        ).fetchone()[0] == 0

                await runtime.close()
                _change_body_bounty_after_acceptance(data_dir)

                runtime = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
                for adapter in _ADAPTERS:
                    user = f"body-trial-{adapter}"
                    accepted_replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "accept-after-restart", accept_operations[adapter]),
                        "接取悬赏 淬体试炼",
                    )
                    assert accepted_replay.code == "BOUNTY_ACCEPTED"
                    assert accepted_replay.data["idempotent_replay"] is True
                    assert accepted_replay.data["target"] == 2

                    board = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "board-before-pve"), "悬赏榜"
                    )
                    offer = next(
                        row for row in board.data["offers"]
                        if row["bounty_key"] == "bounty.body_trial"
                    )
                    assert offer["label"] == "淬体试炼"
                    assert offer["target"] == 2
                    assert offer["reward"] == {
                        "cultivation": 180,
                        "spirit_stones": 25,
                        "item.pill.healing_low": 1,
                    }

                    for index in range(2):
                        start_operation = next(
                            f"{adapter}:body-trial:pve:{index}:{seed}"
                            for seed in range(10_000)
                            if battle_roll_bp(
                                f"{adapter}:body-trial:pve:{index}:{seed}:battle"
                            ) < 2_000
                        )
                        started = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, f"start-{index}", start_operation),
                            "开始探索 短历练",
                        )
                        assert started.code == "EXPLORATION_STARTED"
                        exploration_id = str(started.data["exploration_id"])
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            connection.execute(
                                "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                                (
                                    (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                                    exploration_id,
                                ),
                            )
                        settled = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, f"settle-{index}"),
                            "结算探索",
                        )
                        assert settled.code == "EXPLORATION_SETTLED"
                        assert settled.data["battle_outcome"] == "won"
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            battle = connection.execute(
                                "SELECT enemy_key, status, json_extract(result_json, '$.outcome') "
                                "FROM battle_sessions WHERE battle_id=?",
                                (settled.data["battle_id"],),
                            ).fetchone()
                        assert battle == ("enemy.wood_rat", "settled", "won")

                        board = await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"board-{index}"), "悬赏榜"
                        )
                        offer = next(
                            row for row in board.data["offers"]
                            if row["bounty_key"] == "bounty.body_trial"
                        )
                        assert offer["progress"] == index + 1

                    before_claim = _player_assets(runtime, adapter, user)
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "claim", claim_operations[adapter]),
                        "领取悬赏",
                    )
                    assert claimed.code == "BOUNTY_CLAIMED"
                    assert claimed.data["progress"] == claimed.data["target"] == 2
                    assert claimed.data["rewards"] == {
                        "cultivation": 180,
                        "spirit_stones": 25,
                        "item.pill.healing_low": 1,
                    }
                    after_claim = _player_assets(runtime, adapter, user)
                    assert after_claim[0] == before_claim[0] + 25
                    assert after_claim[1] == before_claim[1] + 180
                    assert after_claim[2].get("item.pill.healing_low", 0) == 1
                    repeated_claim = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "claim-replay", claim_operations[adapter]),
                        "领取悬赏",
                    )
                    assert repeated_claim.data["idempotent_replay"] is True
                    assert repeated_claim.data["rewards"] == claimed.data["rewards"]
                    claim_balances[adapter] = after_claim
                await runtime.close()

                recovered = create_runtime(data_dir=data_dir, adapters=_ADAPTERS)
                try:
                    for adapter in _ADAPTERS:
                        user = f"body-trial-{adapter}"
                        replay = await recovered.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "claim-after-restart", claim_operations[adapter]),
                            "领取悬赏",
                        )
                        assert replay.code == "BOUNTY_CLAIMED"
                        assert replay.data["idempotent_replay"] is True
                        assert _player_assets(recovered, adapter, user) == claim_balances[adapter]
                finally:
                    await recovered.close()
            finally:
                await runtime.close()

    asyncio.run(run())
