"""Whole bounty surface plus short public producer/consumer regressions."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    _reward_outcomes,
    bounty_definitions,
    meets_realm,
    refresh_bounty_candidates,
    reward_map,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import public_project_definitions
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions
from nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_rules import DAO_UNION_STONE_COST, tribulation_definition
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import (
    DAO_UNION_CHALLENGE,
    DAO_UNION_FRAGMENT_REWARD,
    DAO_UNION_MAINLINE,
    DAO_UNION_MAINLINE_STAGE_KEYS,
    DAO_UNION_MAINLINE_STORY_KEY,
    DAO_UNION_WORK,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import resolve_dispatch
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import resolve_route, reward_for as idle_reward

DATA = Path(__file__).parents[1] / "data"


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


def _ctx(operation: str, user: str = "bounty-source") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


def _set_player(runtime, **values):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET " + ", ".join(f"{key}=?" for key in values),
            tuple(values.values()),
        )


def _pool_items(bundle, key):
    return {item for _, rewards in reward_pool_outcomes(key, bundle) for item in rewards}


def _realm_reachable_locations(bundle, realm, layer):
    """Check real directional edges and realm gates, not a location's existence.

    Non-realm preparation (passes, reputation and flags) is listed separately in
    the domain matrix; this helper never treats a locked route as an entrance.
    """
    def allowed(requirements):
        for requirement in requirements:
            if requirement["type"] == "realm" and not meets_realm(
                realm, layer, requirement["realm_key"], requirement["min_layer"], bundle
            ):
                return False
        return True

    edges = [
        (edge["from"], edge["to"], edge.get("requirements", []))
        for region in bundle.list("world_region", include_locked=False)
        for edge in region.get("connections", [])
    ]
    for route in bundle.list("world_cloud_route", include_locked=False):
        if meets_realm(realm, layer, route["realm_key"], route["realm_layer"], bundle):
            edges.extend((source, route["destination"], []) for source in route["source_locations"])
    reached = {"xuantian.new_town"}
    while True:
        additions = {
            destination for source, destination, requirements in edges
            if source in reached and allowed(requirements)
            and allowed(bundle.require("location", destination).get("requirements", []))
        }
        if additions <= reached:
            return reached
        reached.update(additions)


def test_every_bounty_has_a_real_open_target_producer_and_realm_route():
    bundle = ContentBundle.load(DATA)
    recipes = recipe_definitions(bundle)
    problems = []
    modes = bundle.list("exploration_mode", include_locked=False)
    for bounty in bounty_definitions(bundle):
        if bounty.runtime_status != "open":
            continue
        realm, layer = bounty.required_realm or "mortal", bounty.required_layer
        reachable = _realm_reachable_locations(bundle, realm, layer)
        usable_modes = [mode for mode in modes if mode["location_key"] in reachable and meets_realm(
            realm, layer, mode["required_realm"], mode["required_layer"], bundle
        )]
        sources = []
        if bounty.target_kind in {"inventory_gain", "exploration_battle_wins"}:
            for mode in usable_modes:
                items = _pool_items(bundle, mode["reward_pool_key"])
                enemies = []
                if mode["battle_chance_bp"] and mode.get("enemy_pool_key"):
                    enemies = bundle.require("encounter_pool", mode["enemy_pool_key"])["candidates"]
                    for enemy in enemies:
                        profile = bundle.require("enemy", enemy["enemy_key"]).get("combat_profile", {})
                        if profile.get("drop_pool_key"):
                            items |= _pool_items(bundle, profile["drop_pool_key"])
                if bounty.target_kind == "inventory_gain" and bounty.target_key in items:
                    sources.append(mode["key"])
                if bounty.target_kind == "exploration_battle_wins" and any(
                    enemy["enemy_key"] == bounty.target_key for enemy in enemies
                ):
                    sources.append(mode["key"])
            if bounty.target_kind == "inventory_gain":
                for recipe in recipes.values():
                    if bounty.target_key in dict(recipe.outputs) and realm in (
                        recipe.required_realm, *recipe.additional_realms
                    ) and layer >= recipe.min_realm_layer:
                        assert not recipe.required_location or set(recipe.required_location) & reachable, bounty.key
                        sources.append(recipe.key)
                if bounty.target_key == "item.material.cloud_iron" and meets_realm(
                    realm, layer, "foundation", 4, bundle
                ):
                    route = resolve_route("idle.cloud_mine_watch", bundle)
                    assert any(rewards.get(bounty.target_key, 0) >= bounty.target_amount
                               for _, rewards in reward_pool_outcomes(route.pool_key, bundle))
                    sources.append(route.key)  # Prepare the six-hour assignment before accepting.
                if bounty.target_key == "item.tribulation_guard":
                    recipe = bundle.require("endgame_recipe", "recipe.tribulation.guard")
                    assert recipe["output_item"] == bounty.target_key
                    assert recipe["duration_seconds"] < bounty.duration_seconds
                    sources.append(recipe["key"])
                if bounty.target_key == "item.tribulation_token":
                    sources.extend(task["key"] for task in bundle.list("quest", include_locked=False)
                                   if task.get("reward", {}).get(bounty.target_key))
        elif bounty.target_kind == "inventory_delivery":
            assert bounty.target_key == "item.dao_fruit_fragment"
            assert bounty.consume_target
            assert DAO_UNION_FRAGMENT_REWARD - 10 >= bounty.target_amount
            sources.append("quest.dao_union")
        elif bounty.target_kind == "tribulation_trial_wins":
            event = bundle.require("event", "event.heaven_tribulation")
            assert bounty.target_key == "enemy.tribulation_heaven"
            assert any(trial["required_layer"] <= layer for trial in event["trials"])
            sources.append(event["key"])
        elif bounty.target_kind == "dispatch_successes":
            source = resolve_dispatch(bounty.target_key, bundle)
            assert source.duration_seconds * bounty.target_amount < bounty.duration_seconds
            assert dict(source.risk_weights)["success"] > 0
            sources.append(source.key)
        elif bounty.target_kind == "idle_claims":
            source = resolve_route(bounty.target_key, bundle)
            assert source.duration_seconds < bounty.duration_seconds, bounty.key
            sources.append(source.key)
        elif bounty.target_kind == "production_completed":
            sources.extend(recipe.key for recipe in recipes.values() if realm in (
                recipe.required_realm, *recipe.additional_realms
            ) and layer >= recipe.min_realm_layer)
        elif bounty.target_kind == "public_service_completions":
            sources.extend(project.key for project in public_project_definitions(bundle).values()
                           if project.service_sources and not project.required_access_key
                           and not project.required_faction and not project.required_sect_level)
            assert len(sources) >= bounty.target_amount, bounty.key
        if not sources:
            problems.append(f"{bounty.key}: {bounty.target_kind}/{bounty.target_key} at {realm} L{layer}")
    assert not problems, "no reachable public producer:\n" + "\n".join(problems)


def test_all_open_realms_and_paths_have_three_different_available_targets(tmp_path):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            bundle = ContentBundle.load(DATA)
            definitions = bounty_definitions(bundle)
            with runtime.repository._connect() as connection:
                for realm in bundle.list("realm", include_locked=False):
                    for path in bundle.list("path", include_locked=False):
                        connection.execute(
                            "UPDATE players SET stage=?, realm_key=?, realm_layer=?, path_key=?",
                            ("mortal" if realm["key"] == "mortal" else "cultivator",
                             realm["key"], realm["layer_min"], path["key"]),
                        )
                        player = connection.execute("SELECT * FROM players").fetchone()
                        available = [b for b in definitions if b.runtime_status == "open" and
                                     runtime.repository._bounty_player_eligible(connection, player, b, runtime.repository._now())]
                        targets = {(b.target_kind, b.target_key) for b in available}
                        assert len(targets) >= 3, (realm["key"], path["key"], targets)
                        for bounty in refresh_bounty_candidates(available, seed=realm["key"])[:3]:
                            assert reward_map(bounty, bundle, seed=bounty.key, path_key=path["key"],
                                              realm_key=realm["key"], realm_layer=realm["layer_min"])
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def test_daily_batch_uses_configured_weights_without_replacement():
    original = bounty_definitions(ContentBundle.load(DATA))[0]
    candidates = [replace(original, key="light", weight=1), replace(original, key="heavy", weight=99)]
    first = Counter(refresh_bounty_candidates(candidates, seed=f"day:{day}")[0].key for day in range(200))
    assert first["heavy"] > 185 and first["light"] > 0, first
    for day in range(5):
        batch = refresh_bounty_candidates(candidates, seed=f"day:{day}")
        assert {item.key for item in batch} == {"light", "heavy"}
        assert batch == refresh_bounty_candidates(list(reversed(candidates)), seed=f"day:{day}")


def test_all_bounty_reward_candidates_respect_each_eligible_realm_and_path():
    bundle = ContentBundle.load(DATA)
    for bounty in bounty_definitions(bundle):
        for realm in bundle.list("realm", include_locked=False):
            layer = max(realm["layer_min"], bounty.required_layer) if realm["key"] == bounty.required_realm else realm["layer_min"]
            if not meets_realm(realm["key"], layer, bounty.required_realm, bounty.required_layer, bundle):
                continue
            for path in bundle.list("path", include_locked=False):
                if bounty.path_keys and path["key"] not in bounty.path_keys:
                    continue
                outcomes = _reward_outcomes(bundle, bounty.reward_pool_key, path_key=path["key"],
                                            realm_key=realm["key"], realm_layer=layer,
                                            reputation_key=bounty.reputation_key)
                assert outcomes, (bounty.key, realm["key"], path["key"])
                for outcome in outcomes:
                    assert outcome["weight"] > 0 and outcome["rewards"]
                    for key, quantity in outcome["rewards"].items():
                        assert quantity > 0
                        if key.startswith("item."):
                            item = bundle.require("item", key, include_locked=False)
                            if item.get("item_type") in {"weapon", "armor", "accessory"}:
                                assert item.get("path_key") in {None, path["key"]}
                                for requirement in item.get("requirements", []):
                                    if requirement["type"] == "realm":
                                        assert meets_realm(realm["key"], layer, requirement["realm_key"], requirement["min_layer"], bundle)


def test_new_mortal_bounty_completes_via_public_travel_and_gathering(tmp_path, monkeypatch):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            assert (await runtime.dispatch(_ctx("seek"), "寻仙问道")).ok
            assert (await runtime.dispatch(_ctx("accept"), "接取悬赏 镇道备石")).code == "BOUNTY_ACCEPTED"
            travel = await runtime.dispatch(_ctx("travel"), "前往近郊")
            assert travel.ok, travel.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT location_key FROM players").fetchone()[0] == "xuantian.outskirts"
            seed = next(f"stone:{i}" for i in range(1000) if battle_roll_bp(f"stone:{i}:battle") >= 1000
                        and settlement_result("explore.gather_outskirts", f"stone:{i}").get("item.ore.ironstone", 0) >= 2)
            assert (await runtime.dispatch(_ctx(seed), "开始探索 近郊采集")).code == "EXPLORATION_STARTED"
            clock.advance(seconds=31)
            assert (await runtime.dispatch(_ctx("gather-settle"), "结算探索")).ok
            claim = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert claim.code == "BOUNTY_CLAIMED", claim.message
            assert claim.data["progress"] == 2
            assert (await runtime.dispatch(_ctx("claim"), "领取悬赏")).data["idempotent_replay"]
            _set_player(runtime, stage="cultivator", realm_key="qi_sensing", realm_layer=2)
            # Force the exhausted entry first to prove it cannot consume a batch slot.
            monkeypatch.setattr(
                "nonebot_plugin_xiuxian_3.xiuxian.adventures.repository.refresh_bounty_candidates",
                lambda candidates, **kwargs: tuple(sorted(candidates, key=lambda b: b.key != "bounty.mortal.ironstone_order")),
            )
            board = await runtime.repository.get_bounty_board(platform="onebot.v11", platform_user_id="bounty-source")
            assert len([offer for offer in board.offers if offer.status == "available"]) == 3
            assert next(offer for offer in board.offers if offer.key == "bounty.mortal.ironstone_order").status == "claimed"
            monkeypatch.setattr(
                "nonebot_plugin_xiuxian_3.xiuxian.adventures.repository._bounty_daily_counts",
                lambda *args: {b.key: b.daily_limit for b in bounty_definitions()},
            )
            exhausted = await runtime.dispatch(_ctx("exhausted"), "接取悬赏")
            assert exhausted.code == "BOUNTY_DAILY_LIMIT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='exhausted'").fetchone()[0] == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def _qualification_evidence(runtime):
    # The bounded fixture starts after the existing qualification components;
    # fragments and the trial token are obtained only through the public claim.
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute("SELECT id FROM players").fetchone()[0]
        for component in (DAO_UNION_MAINLINE, DAO_UNION_CHALLENGE, DAO_UNION_WORK):
            payload = ({"source": "mainline_runs", "story_key": DAO_UNION_MAINLINE_STORY_KEY,
                        "lane_stage_keys": DAO_UNION_MAINLINE_STAGE_KEYS} if component == DAO_UNION_MAINLINE else {})
            connection.execute(
                "INSERT INTO quest_events(player_id,quest_key,component_key,source_operation_id,outcome,payload_json,created_at) "
                "VALUES (?, 'quest.dao_union', ?, ?, 'success', ?, 'fixture')",
                (player_id, component, component, json.dumps(payload)),
            )


def test_real_qualification_surplus_delivers_and_replays_after_restart(tmp_path):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _set_player(runtime, stage="cultivator", realm_key="void_refining", realm_layer=10,
                        total_cultivation=2998960, world_merit=2000, spirit_stones=DAO_UNION_STONE_COST, path_key="body")
            _qualification_evidence(runtime)
            permit = await runtime.dispatch(_ctx("permit"), "领取合道许可")
            assert permit.ok and permit.data["reward"]["item.dao_fruit_fragment"] == 12, permit.message
            advanced = await runtime.repository.begin_dao_union(platform="onebot.v11", platform_user_id="bounty-source", operation_id="advance")
            assert advanced.player.realm_key == "dao_union"
            accept = await runtime.dispatch(_ctx("accept"), "接取悬赏 道果碎片验收")
            assert accept.code == "BOUNTY_ACCEPTED", accept.message
            assert accept.data["progress"] == accept.data["target"] == 2
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("CREATE TRIGGER fail_claim BEFORE INSERT ON operations "
                                   "WHEN NEW.operation_id='claim' BEGIN SELECT RAISE(ABORT, 'ledger unavailable'); END")
            failed = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert not failed.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert json.loads(connection.execute("SELECT inventory_json FROM players").fetchone()[0])["item.dao_fruit_fragment"] == 2
                assert connection.execute("SELECT status FROM bounty_offers").fetchone()[0] == "accepted"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER fail_claim")
            claim = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert claim.code == "BOUNTY_CLAIMED", claim.message
            assert claim.data["progress"] == 2
            replay = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert replay.data["idempotent_replay"] and replay.data["rewards"] == claim.data["rewards"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert json.loads(connection.execute("SELECT inventory_json FROM players").fetchone()[0]).get("item.dao_fruit_fragment", 0) == 0
            # A depleted finite source must not take a slot in tomorrow's batch.
            with runtime.repository._connect() as connection:
                player = connection.execute("SELECT * FROM players").fetchone()
                definition = next(b for b in bounty_definitions() if b.key == "bounty.dao.fruit_fragment")
                assert not runtime.repository._bounty_player_eligible(connection, player, definition, runtime.repository._now())
        finally:
            await runtime.close()
    asyncio.run(run())


def test_public_transport_receipts_complete_three_different_town_projects(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            assert (await runtime.dispatch(_ctx("seek"), "寻仙问道")).ok
            _set_player(runtime, stage="cultivator", realm_key="foundation", realm_layer=4,
                        stamina=100, stamina_max=100, energy=100, energy_max=100)
            assert (await runtime.dispatch(_ctx("travel"), "前往近郊")).ok
            seed = next(f"cargo:{i}" for i in range(1000) if battle_roll_bp(f"cargo:{i}:battle") >= 1000
                        and settlement_result("explore.gather_outskirts", f"cargo:{i}").get("item.herb.blood_grass", 0) >= 3)
            assert (await runtime.dispatch(_ctx(seed), "开始探索 近郊采集")).ok
            clock.advance(seconds=31)
            assert (await runtime.dispatch(_ctx("cargo-settle"), "结算探索")).ok
            assert (await runtime.dispatch(_ctx("return"), "返回新手城")).ok
            assert (await runtime.dispatch(_ctx("accept"), "接取悬赏 筑基共建差事")).ok
            for index, project in enumerate(("project.town_well", "project.market_road", "project.herb_garden")):
                started = await runtime.dispatch(_ctx(f"transport:{index}"), "开始运输 止血草")
                assert started.code == "ROUTE_STARTED", started.message
                clock.advance(minutes=21)
                settled = await runtime.dispatch(_ctx(f"receipt:{index}"), "结算运输")
                assert settled.code == "ROUTE_SETTLED", settled.message
                contribution = await runtime.dispatch(_ctx(f"contribute:{index}"),
                                                     f"贡献公共项目 {project} 运输 {settled.operation_id}")
                assert contribution.code == "PROJECT_CONTRIBUTED", contribution.message
                board = await runtime.repository.get_bounty_board(platform="onebot.v11", platform_user_id="bounty-source")
                offer = next(offer for offer in board.offers if offer.key == "bounty.foundation.service_round")
                assert offer.progress == index + 1
                if index == 0:
                    reused = await runtime.dispatch(_ctx("reuse"),
                                                    f"贡献公共项目 project.market_road 运输 {settled.operation_id}")
                    assert reused.code == "PROJECT_SOURCE_ALREADY_USED"
                assert (await runtime.dispatch(_ctx(f"return:{index}"), "返回新手城")).ok
            claim = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert claim.code == "BOUNTY_CLAIMED", claim.message
            assert (await runtime.dispatch(_ctx("claim"), "领取悬赏")).data["idempotent_replay"]
        finally:
            await runtime.close()
    asyncio.run(run())


def test_tribulation_bounty_counts_real_trial_battles_and_keeps_snapshot(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _qualification_evidence(runtime)
            assert (await runtime.dispatch(_ctx("permit"), "领取合道许可")).ok
            _set_player(runtime, stage="cultivator", realm_key="tribulation", realm_layer=3,
                        location_key="tribulation.sky_terrace", path_key="body", endgame_status="tribulation",
                        qualification_json=json.dumps({"body": 2000, "agility": 2000}))
            accepted = await runtime.dispatch(_ctx("accept"), "接取悬赏 天劫回响")
            assert accepted.code == "BOUNTY_ACCEPTED"
            early = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert early.code == "BOUNTY_NOT_COMPLETE"
            trial = await runtime.dispatch(_ctx("trial"), "开始天劫试炼 身心劫")
            assert trial.code == "TRIAL_STARTED", trial.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle = connection.execute("SELECT battle_type, result_json FROM battle_sessions WHERE battle_id=?", (trial.data["battle_id"],)).fetchone()
                frozen = connection.execute("SELECT snapshot_json FROM bounty_offers").fetchone()[0]
            assert battle[0] == "pve.tribulation_trial" and json.loads(battle[1])["outcome"] == "won"
            with runtime.repository._connect() as connection:
                player = connection.execute("SELECT * FROM players").fetchone()
                definition = next(b for b in bounty_definitions() if b.key == "bounty.tribulation.echo")
                assert not runtime.repository._bounty_player_eligible(connection, player, definition, clock())
            await runtime.close()
            # Closing the current definition must not invalidate the accepted target.
            content_dir = tmp_path
            shutil.copytree(DATA, content_dir, dirs_exist_ok=True)
            path = content_dir / "任务/悬赏.json"
            data = json.loads(path.read_text())
            bounty = next(row for row in data["records"] if row["key"] == "bounty.tribulation.echo")
            bounty.update(status="locked", target_amount=99)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            claim = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert claim.code == "BOUNTY_CLAIMED", claim.message
            assert claim.data["progress"] == claim.data["target"] == 1
            assert (await runtime.dispatch(_ctx("claim"), "领取悬赏")).data["idempotent_replay"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT snapshot_json FROM bounty_offers").fetchone()[0] == frozen
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("key", ["bounty.idle.demon_post", "bounty.idle.dao_post"])
def test_idle_bounty_rejects_missing_public_source_prerequisites(tmp_path, key):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _set_player(runtime, stage="cultivator", realm_key="dao_union", realm_layer=1)
            result = await runtime.dispatch(_ctx("accept"), f"接取悬赏 {key}")
            assert result.code == "BOUNTY_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='accept'").fetchone()[0] == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def test_delivery_kind_cannot_be_configured_as_a_free_inventory_check(tmp_path):
    shutil.copytree(DATA, tmp_path / "data")
    path = tmp_path / "data/任务/悬赏.json"
    data = json.loads(path.read_text())
    next(row for row in data["records"] if row["key"] == "bounty.dao.fruit_fragment")["consume_target"] = False
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="inventory_delivery must consume"):
        bounty_definitions(ContentBundle.load(tmp_path / "data"))


def test_trial_kind_rejects_an_enemy_without_a_public_trial(tmp_path):
    shutil.copytree(DATA, tmp_path / "data")
    path = tmp_path / "data/任务/悬赏.json"
    data = json.loads(path.read_text())
    next(row for row in data["records"] if row["key"] == "bounty.tribulation.echo")["target_key"] = "enemy.wood_rat"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="must reference the tribulation trial enemy"):
        bounty_definitions(ContentBundle.load(tmp_path / "data"))


@pytest.mark.parametrize("completed,layer", [(1, 3), (3, 10)])
def test_trial_bounty_rejects_exhausted_or_not_yet_reachable_trials(tmp_path, completed, layer):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _set_player(runtime, stage="cultivator", realm_key="tribulation", realm_layer=layer)
            event = tribulation_definition()
            # Completed history is a refusal fixture, not injected bounty progress.
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players").fetchone()[0]
                for key in event.trial_order[:completed]:
                    connection.execute(
                        "INSERT INTO tribulation_trial_sessions(session_id,player_id,operation_id,trial_key,status,"
                        "starts_at,ends_at,created_at,updated_at) VALUES (?,?,?,?,'succeeded',?,?,?,?)",
                        (key, player_id, key, key, *("fixture",) * 4),
                    )
            denied = await runtime.dispatch(_ctx("accept"), "接取悬赏 天劫回响")
            assert denied.code == "BOUNTY_REQUIREMENT_MISSING", denied.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='accept'").fetchone()[0] == 0
            if completed == 1:
                _set_player(runtime, realm_layer=6)
                accepted = await runtime.dispatch(_ctx("retry"), "接取悬赏 天劫回响")
                assert accepted.code == "BOUNTY_ACCEPTED", accepted.message
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("preparation", [{"inventory_json": json.dumps({"item.permit.cloud_mine": 1})},
                                         {"subprofession_key": "mining"}])
def test_mine_preparation_cannot_bypass_the_realm_of_a_reachable_source(tmp_path, preparation):
    async def run():
        runtime = create_runtime(data_dir=tmp_path)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _set_player(runtime, stage="cultivator", realm_key="foundation", realm_layer=1, **preparation)
            denied = await runtime.dispatch(_ctx("accept"), "接取悬赏 云铁矿区悬赏")
            assert denied.code == "BOUNTY_REQUIREMENT_MISSING", denied.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM bounty_offers").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='accept'").fetchone()[0] == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def test_foundation_cloud_iron_uses_real_prepared_idle_reward(tmp_path, monkeypatch):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            _set_player(runtime, stage="cultivator", realm_key="foundation", realm_layer=4, energy=100, energy_max=100)
            route = resolve_route("idle.cloud_mine_watch")
            seed = next(UUID(int=i) for i in range(100) if idle_reward(route, UUID(int=i).hex, fallback=False)["item.material.cloud_iron"] == 3)
            values = iter((UUID(int=100), seed))
            monkeypatch.setattr("nonebot_plugin_xiuxian_3.xiuxian.specials.idle_repository.uuid4", lambda: next(values))
            started = await runtime.dispatch(_ctx("idle-start"), "开始挂机 矿区看守")
            assert started.code == "IDLE_STARTED", started.message
            clock.advance(hours=5)
            accepted = await runtime.dispatch(_ctx("accept"), "接取悬赏 云铁矿区悬赏")
            assert accepted.code == "BOUNTY_ACCEPTED", accepted.message
            clock.advance(hours=1, seconds=1)
            claimed = await runtime.dispatch(_ctx("idle-claim"), "领取挂机")
            assert claimed.code == "IDLE_CLAIMED", claimed.message
            result = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert result.code == "BOUNTY_CLAIMED" and result.data["progress"] == 3, result.message
        finally:
            await runtime.close()
    asyncio.run(run())


def test_higher_realm_tea_bounty_uses_public_gathering_and_production(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await runtime.dispatch(_ctx("create"), "开始修仙")).ok
            for index, command in enumerate(("寻仙问道", "完成引导 阅读", "前往近郊",
                                             "完成引导 采集", "完成引导 炼丹", "选择道途 辅修 烹饪")):
                result = await runtime.dispatch(_ctx(f"guide:{index}"), command)
                assert result.ok, result.message
            assert (await runtime.dispatch(_ctx("return-town"), "返回新手城")).ok
            _set_player(runtime, stage="cultivator", realm_key="foundation", realm_layer=1,
                        stamina=100, stamina_max=100, energy=100, energy_max=100)
            assert (await runtime.dispatch(_ctx("to-spring"), "前往 灵泉谷")).code == "TRAVEL_STARTED"
            clock.advance(minutes=5)
            assert (await runtime.dispatch(_ctx("arrive-spring"), "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await runtime.dispatch(_ctx("accept"), "接取悬赏 云灵茶试饮")).code == "BOUNTY_ACCEPTED"
            for index in range(2):
                started = await runtime.dispatch(_ctx(f"tea-gather:{index}"), "开始探索 灵泉采集")
                assert started.code == "EXPLORATION_STARTED", started.message
                clock.advance(minutes=3)
                assert (await runtime.dispatch(_ctx(f"gather:{index}"), "结算探索")).ok
            started = await runtime.dispatch(_ctx("tea-produce"), "开始生产 云灵茶")
            assert started.code == "PRODUCTION_STARTED", started.message
            clock.advance(seconds=61)
            assert (await runtime.dispatch(_ctx("produce-claim"), "领取生产")).code == "PRODUCTION_COMPLETED"
            claimed = await runtime.dispatch(_ctx("claim"), "领取悬赏")
            assert claimed.code == "BOUNTY_CLAIMED" and claimed.data["progress"] == 1, claimed.message
        finally:
            await runtime.close()
    asyncio.run(run())
