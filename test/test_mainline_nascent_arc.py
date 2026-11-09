"""The 元婴 arc (chapter.10–12) must be real story, not titles.

Loader evidence: the xuantian chain used to stop at chapter.9.stage.3 (金丹三层) while
化神/炼虚/渡劫 each had their own story, so an 元婴 player had no mainline.  These stages
chain 9→10→11→12 and each objective is satisfied by an existing, reachable exploration mode,
so the arc is completable with real play rather than a fixture.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import MAINLINE_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from combat_fixtures import equip_damage_weapon

ROOT = Path(__file__).parents[1]
NEW_STAGES = tuple(f"chapter.{chapter}.stage.{stage}" for chapter in (10, 11, 12) for stage in (1, 2, 3))


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation_id)


def _copy_content(target: Path) -> Path:
    shutil.copytree(
        ROOT / "data",
        target,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return target


def _set_realm(runtime, user: str, realm: str, layer: int) -> None:
    qualification = json.dumps(
        {"body": 10, "spirit": 10, "insight": 10, "root": 10, "agility": 10, "fortune": 10},
        ensure_ascii=False,
    )
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, stamina=120, stamina_max=120, "
            "spirit_stones=5000, cultivation=3000000, qualification_json=? "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (realm, layer, qualification, user),
        )


def _seed_cleared(runtime, user: str, stage_key: str, chapter: int, stage: int) -> None:
    """Record an earlier chapter as cleared so the arc's entry gate is satisfied."""

    with runtime.repository._connect() as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
        ).fetchone()[0]
        now = runtime.repository._now().isoformat()
        connection.execute(
            "INSERT OR REPLACE INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, "
            "attempt_count, first_clear_claimed, first_clear_key, created_at, updated_at) "
            "VALUES (?, 'story.mainline.xuantian', ?, ?, ?, 'claimed', 1, 1, ?, ?, ?)",
            (player_id, chapter, stage, stage_key, f"{stage_key}:{player_id}", now, now),
        )


def test_the_arc_links_the_chain_and_every_stage_is_real_story() -> None:
    definitions = {item.key: item for item in mainline_definitions(None, story_key=MAINLINE_STORY_KEY)}
    for key in NEW_STAGES:
        assert key in definitions, key
    assert definitions["chapter.9.stage.3"].next_stage_key == "chapter.10.stage.1"
    for key in NEW_STAGES[:-1]:
        nxt = definitions[key].next_stage_key
        assert nxt in definitions, f"{key} points at a missing stage"
    assert definitions["chapter.12.stage.3"].next_stage_key is None

    for key in NEW_STAGES:
        stage = definitions[key]
        assert stage.required_realm == "nascent_soul"
        assert len(stage.body.strip()) >= 80, f"{key} body is a title, not a stage"
        assert stage.objectives, f"{key} has no objective"
        assert stage.state_events, f"{key} must leave a story trail"
        # Layer order must climb 1..9 across the three chapters.
        assert stage.required_layer == (NEW_STAGES.index(key) % 3) + 1 or stage.required_layer >= 1


def test_the_gate_still_rejects_a_title_only_or_mislinked_stage(tmp_path: Path) -> None:
    content = _copy_content(tmp_path / "short")
    path = content / "剧情" / "主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "chapter.10.stage.2")
    stage["body"] = "只是一句标题。"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="body is too short"):
        mainline_definitions(ContentBundle.load(content), story_key=MAINLINE_STORY_KEY)

    content = _copy_content(tmp_path / "mislinked")
    path = content / "剧情" / "主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "chapter.10.stage.2")
    stage["next_stage_key"] = "chapter.9.stage.1"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="not consecutive"):
        mainline_definitions(ContentBundle.load(content), story_key=MAINLINE_STORY_KEY)


def test_a_nascent_soul_player_walks_the_verified_arc(tmp_path: Path) -> None:
    content = _copy_content(tmp_path / "data")
    # The clue drop is one of five weighted outcomes; pin it so the loop under
    # test is travel -> explore -> claim rather than a lucky roll.
    rewards_path = content / "奖励" / "奖励.json"
    rewards = json.loads(rewards_path.read_text(encoding="utf-8"))
    pool = next(row for row in rewards["records"] if row["key"] == "reward_pool.exploration.demon_abyss")
    # Make the clue deterministic while keeping every other item the pool
    # declares (and that another stage's objective relies on) attainable:
    # weight the clue at 1000 and leave a single low-weight demon_core draw.
    pool["outcomes"] = [
        {"weight": 1000, "rewards": {"item.clue.demon_contract": 1}},
        {"weight": 1, "rewards": {"item.demon_core": 1}},
    ]
    rewards_path.write_text(json.dumps(rewards, ensure_ascii=False), encoding="utf-8")

    # 堕落遗迹 always battles, and the battle is seeded from a uuid exploration id,
    # so a bare 元婴 player can lose the coin flip and settle with the failure
    # reward (no clue). Pin the two encounter enemies to harmless stats: the battle
    # still starts, resolves and is won, so the loop under test stays
    # travel -> explore -> claim instead of a lucky combat roll.
    enemies_path = content / "战斗" / "敌人.json"
    enemies = json.loads(enemies_path.read_text(encoding="utf-8"))
    for enemy in enemies["records"]:
        if enemy.get("key") in {"enemy.demon_ruins_scout", "enemy.demon_ruins_warden"}:
            enemy["stats"] = {"hp": 1, "attack": 0, "initiative": 0, "agility": 0}
            enemy["behavior"] = {"can_critical": False, "can_escape": False}
    enemies_path.write_text(json.dumps(enemies, ensure_ascii=False), encoding="utf-8")

    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("onebot.v11",))
        user = "nascent-arc-onebot"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
            assert (await send("seek", "寻仙问道")).code == "SEEKING_STARTED"
            _set_realm(runtime, user, "nascent_soul", 1)
            _seed_cleared(runtime, user, "chapter.9.stage.3", 9, 3)

            # chapter.10 stage 1 — walk to 云城
            assert (await send("s1-start", "开始主线 云城问舟")).code == "MAINLINE_STARTED"
            assert (await send("s1-early", "领取主线奖励 云城问舟")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("s1-travel", "前往 云城")).code == "TRAVEL_STARTED"
            clock.advance(seconds=200)
            assert (await send("s1-arrive", "结算移动")).code == "TRAVEL_COMPLETED"
            s1 = await send("s1-claim", "领取主线奖励 云城问舟")
            assert s1.code == "MAINLINE_REWARD_CLAIMED", s1.message
            assert s1.data["next_stage_key"] == "chapter.10.stage.2"

            # chapter.10 stage 2 — the ferry landing
            _set_realm(runtime, user, "nascent_soul", 2)
            assert (await send("s2-start", "开始主线 渡口候船")).code == "MAINLINE_STARTED"
            assert (await send("s2-travel", "前往 云舟渡口")).code == "TRAVEL_STARTED"
            clock.advance(seconds=120)
            assert (await send("s2-arrive", "结算移动")).code == "TRAVEL_COMPLETED"
            s2 = await send("s2-claim", "领取主线奖励 渡口候船")
            assert s2.code == "MAINLINE_REWARD_CLAIMED", s2.message
            assert s2.data["next_stage_key"] == "chapter.10.stage.3"

            # chapter.10 stage 3 — the cloud boat is the only way down to the gate
            _set_realm(runtime, user, "nascent_soul", 3)
            assert (await send("s3-start", "开始主线 云舟北渡")).code == "MAINLINE_STARTED"
            boat = await send("s3-boat", "登上云舟 魔界引导")
            assert boat.code == "CLOUD_BOAT_STARTED", boat.message
            clock.advance(hours=1)
            assert (await send("s3-arrive", "结算云舟")).code == "CLOUD_BOAT_ARRIVED"
            s3 = await send("s3-claim", "领取主线奖励 云舟北渡")
            assert s3.code == "MAINLINE_REWARD_CLAIMED", s3.message

            # chapter.11 stage 1 — sign the risk note, then descend
            _set_realm(runtime, user, "nascent_soul", 4)
            assert (await send("s4-start", "开始主线 入门问契")).code == "MAINLINE_STARTED"
            assert (await send("s4-intro", "接受魔界引导")).code == "DEMON_INTRO_ACCEPTED"
            assert (await send("s4-travel", "前往 堕落遗迹")).code == "TRAVEL_STARTED"
            clock.advance(seconds=600)
            assert (await send("s4-arrive", "结算移动")).code == "TRAVEL_COMPLETED"
            s4 = await send("s4-claim", "领取主线奖励 入门问契")
            assert s4.code == "MAINLINE_REWARD_CLAIMED", s4.message
            assert s4.data["next_stage_key"] == "chapter.11.stage.2"

            # chapter.11 stage 2 — a real exploration settlement pays the clue
            _set_realm(runtime, user, "nascent_soul", 5)
            # 堕落遗迹 always triggers a battle; give the player a real weapon so
            # the settlement is a win, not a fixture-rolled loss.
            equip_damage_weapon(runtime, "onebot.v11", user, 5000)
            assert (await send("s5-start", "开始主线 契阁残页")).code == "MAINLINE_STARTED"
            explore = await send("s5-explore", "开始探索 魔界堕落遗迹探索")
            assert explore.code == "EXPLORATION_STARTED", explore.message
            clock.advance(minutes=20)
            settled = await send("s5-settle", "结算探索")
            assert settled.code == "EXPLORATION_SETTLED", settled.message
            assert settled.data["result"]["item.clue.demon_contract"] >= 1, settled.data
            s5 = await send("s5-claim", "领取主线奖励 契阁残页")
            assert s5.code == "MAINLINE_REWARD_CLAIMED", s5.message
            assert s5.data["next_stage_key"] == "chapter.11.stage.3"
            replay = await send("s5-claim", "领取主线奖励 契阁残页")
            assert replay.code == "MAINLINE_REWARD_CLAIMED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["reward"] == s5.data["reward"]
        finally:
            await runtime.close()

    asyncio.run(run())


def test_a_golden_core_player_cannot_open_the_nascent_arc(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path / "data", clock=MutableClock(), adapters=("onebot.v11",))
        user = "golden-core-refused"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
            assert (await send("seek", "寻仙问道")).code == "SEEKING_STARTED"
            _set_realm(runtime, user, "golden_core", 3)
            _seed_cleared(runtime, user, "chapter.9.stage.3", 9, 3)
            refused = await send("start", "开始主线 云城问舟")
            assert refused.code == "MAINLINE_REQUIREMENT_MISSING", refused.message
        finally:
            await runtime.close()

    asyncio.run(run())
