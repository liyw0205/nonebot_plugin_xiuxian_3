"""Content contract for the four depth bounties."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    bounty_definition,
    bounty_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

DATA = Path(__file__).parents[1] / "data"
KEYS = (
    "bounty.abyss_core",
    "bounty.abyss_clue",
    "bounty.domain_soul",
    "bounty.domain_fragment_raid",
)


def _replace_bounty(bundle, record_key, **changes):
    records = dict(bundle._records)
    row = copy.deepcopy(records["bounty", record_key])
    row.update(changes)
    records["bounty", record_key] = row
    return replace(bundle, _records=records)


def test_depth_bounties_resolve_their_targets_and_pools() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = {definition.key: definition for definition in bounty_definitions(bundle)}
    for key in KEYS:
        assert key in definitions
    goals = {
        "bounty.abyss_core": ("item.demon_core", 3),
        "bounty.abyss_clue": ("item.clue.demon_contract", 1),
        "bounty.domain_soul": ("item.soul_crystal", 2),
        "bounty.domain_fragment_raid": ("item.domain_core_fragment", 4),
    }
    for key, (target, amount) in goals.items():
        definition = bounty_definition(key, bundle)
        assert definition.target_key == target
        assert definition.target_amount == amount
        assert definition.required_realm == "soul_transformation"
        row = bundle.get("bounty", key, include_locked=True)
        assert bundle.has("reward", row["reward_pool_key"], include_locked=False)
        assert bundle.has("item", target, include_locked=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"target_amount": 0},
        {"target_key": "item.missing"},
        {"reward_pool_key": "reward_pool.missing"},
        {"required_realm": "realm.missing"},
    ],
)
def test_depth_bounty_content_rejects_broken_records(changes: dict) -> None:
    bundle = _replace_bounty(ContentBundle.load(DATA), KEYS[0], **changes)
    with pytest.raises((ContentError, ValueError, KeyError)):
        bounty_definitions(bundle)


def test_depth_bounty_enters_a_daily_batch_and_can_be_accepted() -> None:
    import asyncio
    import shutil
    from datetime import datetime, timedelta, timezone
    from tempfile import TemporaryDirectory

    from nonebot_plugin_xiuxian_3.contracts import CommandContext
    from nonebot_plugin_xiuxian_3.runtime import create_runtime

    label = bounty_definition("bounty.abyss_core", ContentBundle.load(DATA)).label

    def ctx(user: str, name: str, operation_id: str = "") -> CommandContext:
        return CommandContext(
            adapter="web", user_id=user, request_id=name, operation_id=operation_id
        )

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            shutil.copytree(DATA, Path(data_dir) / "data")
            clock = datetime(2026, 9, 22, 6, tzinfo=timezone.utc)
            runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: clock)
            user = "bounty-depth"
            try:
                await runtime.dispatch(ctx(user, "create"), "开始修仙")
                await runtime.dispatch(ctx(user, "seek"), "寻仙问道")
                import sqlite3

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='soul_transformation', realm_layer=4 "
                        "WHERE platform_user_id = ?",
                        (user,),
                    )
                seen: list[str] = []
                for _ in range(90):
                    board = await runtime.dispatch(ctx(user, "board"), "悬赏榜")
                    labels = [item["label"] for item in board.data["offers"]]
                    seen.append("|".join(labels))
                    if label in labels:
                        break
                    clock = clock + timedelta(days=1)
                else:
                    raise AssertionError(
                        "the depth bounty never entered a three-slot daily batch; "
                        f"first batches: {seen[:5]}"
                    )
                accepted = await runtime.dispatch(
                    ctx(user, "accept", "depth-accept"), f"接取悬赏 {label}"
                )
                assert accepted.ok, accepted
                duplicate = await runtime.dispatch(
                    ctx(user, "accept-2", "depth-accept-2"), f"接取悬赏 {label}"
                )
                assert duplicate.ok is False
            finally:
                await runtime.close()

    asyncio.run(run())
