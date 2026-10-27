"""Contracts for the staged onboarding guides.

The guide table now carries its own tier, handles and presentation, so the
suite pins two things at once: the data contract (six guides, two tiers, every
requirement/cost/reward closed) and the runtime behaviour (a mortal graduates
on the mortal trio alone, a cultivator can actually finish the new guides, and
replaying either tier neither re-charges resources nor re-grants rewards).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.player.intro_rules import (
    INTRO_GUIDES,
    STAGE_CULTIVATOR,
    STAGE_MORTAL,
    guide_alias_map,
    guide_definitions,
    guides_for_stage,
    intro_complete,
    mortal_guides,
    resolve_guide,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TIER_OF = {
    "guide.read_world": STAGE_MORTAL,
    "guide.gather_blood_grass": STAGE_MORTAL,
    "guide.choose_service": STAGE_MORTAL,
    "guide.mine_entry": STAGE_CULTIVATOR,
    "guide.dispatch_entry": STAGE_CULTIVATOR,
    "guide.secret_realm_entry": STAGE_CULTIVATOR,
}
CULTIVATOR_GUIDES = ("guide.mine_entry", "guide.dispatch_entry", "guide.secret_realm_entry")


def _context(user: str, request: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="qq.official",
        user_id=user,
        request_id=request,
        operation_id=operation_id,
        can_write_assets=True,
    )


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def test_guide_table_ships_two_tiers_with_closed_requirements() -> None:
    definitions = guide_definitions(_bundle())
    by_key = {definition["key"]: definition for definition in definitions}

    assert len(definitions) == 6
    assert set(by_key) == set(TIER_OF)
    for key, tier in TIER_OF.items():
        assert by_key[key]["stage"] == tier, key
        # Exactly one stage requirement, and it names this record's own tier.
        assert by_key[key]["stage"] in {STAGE_MORTAL, STAGE_CULTIVATOR}
    assert mortal_guides(_bundle()) == INTRO_GUIDES
    assert {definition["key"] for definition in guides_for_stage(STAGE_MORTAL, _bundle())} == set(
        INTRO_GUIDES
    )
    assert {definition["key"] for definition in guides_for_stage(STAGE_CULTIVATOR, _bundle())} == set(
        CULTIVATOR_GUIDES
    )


def test_guide_handles_and_rewards_stay_closed() -> None:
    bundle = _bundle()
    definitions = guide_definitions(bundle)
    aliases = guide_alias_map(bundle)
    for definition in definitions:
        key = definition["key"]
        # Every record is reachable by its own command and by every alias.
        assert resolve_guide(definition["command"], bundle) == key
        assert resolve_guide(key, bundle) == key
        for alias in definition["aliases"]:
            assert aliases[alias] == key, (key, alias)
        # Rewards only hand out items that already exist in content.
        item_key = definition["item_key"]
        if item_key is not None:
            assert bundle.has("item", item_key, include_locked=False)
        # Costs and refunds name a real resource and never refund more than spent.
        cost = definition["cost"]
        refund = definition["failure_refund"]
        if cost:
            assert cost["resource_key"] in {"stamina", "energy"}
            assert cost["amount"] > 0
        if refund:
            assert cost and refund["resource_key"] == cost["resource_key"]
            assert 0 < refund["amount"] <= cost["amount"]
        # Location requirements name open places.
        for location in definition["locations"]:
            assert bundle.has("location", location, include_locked=True), location
    # The new tier must not invent new locations or items.
    for key in CULTIVATOR_GUIDES:
        definition = next(item for item in definitions if item["key"] == key)
        assert definition["locations"] == ()
        assert definition["item_key"] is None
        assert definition["cost"] == {}


def test_mortal_graduation_only_counts_the_mortal_trio() -> None:
    bundle = _bundle()
    assert intro_complete([], bundle) is False
    assert intro_complete(list(INTRO_GUIDES), bundle) is True

    # Completing realm-gated guides can never substitute for the onboarding trio.
    partial = [CULTIVATOR_GUIDES[0], CULTIVATOR_GUIDES[1], INTRO_GUIDES[0], INTRO_GUIDES[1]]
    assert intro_complete(partial, bundle) is False
    # Conversely the trio alone is enough even without any later guide.
    assert intro_complete(list(INTRO_GUIDES), bundle) is True


def test_stage_progress_is_filtered_per_tier() -> None:
    bundle = _bundle()
    mortal_keys = {definition["key"] for definition in guides_for_stage(STAGE_MORTAL, bundle)}
    cultivator_keys = {
        definition["key"] for definition in guides_for_stage(STAGE_CULTIVATOR, bundle)
    }
    # A mortal is never measured against the realm-gated guides...
    assert cultivator_keys.isdisjoint(mortal_keys)
    assert mortal_keys == set(INTRO_GUIDES)
    # ...and a cultivator is no longer measured against the onboarding trio.
    assert cultivator_keys == set(CULTIVATOR_GUIDES)


def test_cultivator_guides_complete_and_replay_without_side_effects() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "guide-cultivator"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            # A graduated player is already past onboarding.
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='foundation',"
                    " realm_layer=1, stamina=20, stamina_max=20, energy=20, energy_max=20,"
                    " spirit_stones=1000 WHERE platform_user_id=?",
                    (user,),
                )

            for index, key in enumerate(CULTIVATOR_GUIDES):
                definition = next(
                    item for item in guide_definitions(runtime.content) if item["key"] == key
                )
                operation = f"guide-op-{index}"
                first = await runtime.dispatch(
                    _context(user, f"first-{index}", operation),
                    f"完成引导 {definition['command']}",
                )
                assert first.ok, (key, first.code, first.message)
                assert first.code == "INTRO_COMPLETED"
                assert first.data["idempotent_replay"] is False
                assert key in first.data["intro_flags"]
                # Free lessons leave resources untouched.
                assert first.data["stamina"] == 20
                assert first.data["energy"] == 20

                replay = await runtime.dispatch(
                    _context(user, f"replay-{index}", operation),
                    f"完成引导 {definition['command']}",
                )
                assert replay.ok, (key, replay.code)
                assert replay.data["idempotent_replay"] is True
                assert replay.data["stamina"] == 20
                assert replay.data["energy"] == 20
                assert replay.data["intro_flags"] == first.data["intro_flags"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                flags = json.loads(
                    connection.execute(
                        "SELECT intro_json FROM players WHERE platform_user_id=?", (user,)
                    ).fetchone()[0]
                ).get("flags", [])
            for key in CULTIVATOR_GUIDES:
                assert key in flags
            # A cultivator never graduates: the onboarding trio is untouched.
            assert set(INTRO_GUIDES).isdisjoint(flags)
            await runtime.close()

    asyncio.run(run())


def test_cultivator_guide_is_refused_before_graduation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "guide-mortal"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            definition = next(
                item
                for item in guide_definitions(runtime.content)
                if item["key"] == "guide.mine_entry"
            )
            refused = await runtime.dispatch(
                _context(user, "too-early"), f"完成引导 {definition['command']}"
            )
            assert refused.code == "PLAYER_STAGE_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                flags = json.loads(
                    connection.execute(
                        "SELECT intro_json FROM players WHERE platform_user_id=?", (user,)
                    ).fetchone()[0]
                ).get("flags", [])
            assert flags == []
            await runtime.close()

    asyncio.run(run())


def test_mortal_onboarding_still_graduates_and_replays() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "guide-mortal-flow"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok

            read = await runtime.dispatch(
                _context(user, "read", "mortal-read"), "完成引导 阅读"
            )
            assert read.code == "INTRO_COMPLETED"
            assert read.data["intro_flags"] == ("guide.read_world",)
            replay = await runtime.dispatch(
                _context(user, "read-again", "mortal-read"), "完成引导 阅读"
            )
            assert replay.data["idempotent_replay"] is True

            travel = await runtime.dispatch(_context(user, "travel"), "前往近郊")
            assert travel.code == "TRAVEL_COMPLETED"
            stamina_before = travel.data["stamina"]

            gather = await runtime.dispatch(
                _context(user, "gather", "mortal-gather"), "完成引导 采集"
            )
            assert gather.code == "INTRO_COMPLETED"
            assert gather.data["stamina"] == stamina_before - 2
            assert 1 <= gather.data["item_quantity"] <= 2
            gather_replay = await runtime.dispatch(
                _context(user, "gather-again", "mortal-gather"), "完成引导 采集"
            )
            assert gather_replay.data["idempotent_replay"] is True
            # Replay must not re-charge stamina or re-grant the herb.
            assert gather_replay.data["stamina"] == gather.data["stamina"]
            assert (
                gather_replay.data["inventory"]["item.herb.blood_grass"]
                == gather.data["inventory"]["item.herb.blood_grass"]
            )

            service = await runtime.dispatch(
                _context(user, "service", "mortal-service"), "完成引导 炼丹"
            )
            assert service.code == "INTRO_COMPLETED"
            assert service.data["stage"] == "seeker"
            assert service.data["stage_advanced"] is True
            assert service.data["energy"] == 28

            entered = await runtime.dispatch(_context(user, "enter"), "选择道途 体修")
            assert entered.code == "CULTIVATION_ENTERED"
            assert entered.data["stage"] == "cultivator"
            await runtime.close()

    asyncio.run(run())


def test_unknown_guide_is_rejected_without_mutation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "guide-unknown"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            unknown = await runtime.dispatch(_context(user, "unknown"), "完成引导 观星")
            assert unknown.code == "INVALID_GUIDE"
            # The teaching lesson still requires naming a service.
            unnamed = await runtime.dispatch(_context(user, "no-service"), "完成引导 生产")
            assert unnamed.code == "INVALID_GUIDE"
            await runtime.close()

    asyncio.run(run())
