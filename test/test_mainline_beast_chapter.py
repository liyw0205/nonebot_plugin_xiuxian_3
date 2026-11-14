"""chapter.13 万兽山 must be a real, gated, playable L10 chain.

元婴 configures `layer_min 1 / layer_max 10`, but the chain used to end at
`chapter.12.stage.3` (L9) with `next_stage_key: null`, so the realm's cap layer
had no mainline at all.  These tests pin chapter.13 as the third 元婴 chapter,
under the same vertical-slice gate as every other realm, and prove 13.1/13.2/13.3
end to end through public commands.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    MAINLINE_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from combat_fixtures import equip_damage_weapon

ROOT = Path(__file__).parents[1]
BEAST_STAGES = tuple(f"chapter.13.stage.{stage}" for stage in (1, 2, 3))


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation_id)


def _copy_content(path: Path) -> Path:
    target = path / "data"
    shutil.copytree(
        ROOT / "data",
        target,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return target


def _pin_beast_content(content: Path) -> None:
    """Weight 兽血 at 1000:1 so the hunt pays the objective inside 日限 2.

    The fight itself is settled by a 50k-damage weapon (see `test_beast_hills`):
    `enemy.beast_guardian` is 7500 hp / 480 attack and its stats are still
    resolved from the bundled enemy table, so rewriting the tmp content copy's
    `stats` does not change the battle.  Every other declared pool outcome stays
    attainable, which 化神's `domain_frontier.protect.5` requires.
    """

    rewards_path = content / "奖励" / "奖励.json"
    rewards = json.loads(rewards_path.read_text(encoding="utf-8"))
    pool = next(
        row
        for row in rewards["records"]
        if row["key"] == "reward_pool.exploration.beast_hunt"
    )
    pool["outcomes"] = [
        {"weight": 1000, "rewards": {"item.beast_blood": 1}},
        # 化神's domain_frontier.protect.5 needs item.clue.beast_bloodline from
        # this same pool; dropping that outcome makes the whole story
        # unloadable ("item is not attainable"), so keep it attainable.
        {"weight": 1, "rewards": {"item.clue.beast_bloodline": 1}},
        {"weight": 1, "rewards": {"faction_reputation.beast": 15}},
    ]
    rewards_path.write_text(json.dumps(rewards, ensure_ascii=False), encoding="utf-8")



def _stage_ready_player(
    runtime, user: str, *, realm: str, layer: int, location: str = "xuantian.new_town"
) -> None:
    """Make a player who has already cleared 元婴 L9 and stands at 青石镇.

    `max_hp`/`initiative` are set because 万兽山 always battles: without them the
    player snapshot carries no combat stats and the fight resolves as an instant
    0-round loss (same fixture shape as `test_beast_hills`).
    """

    qualification = json.dumps(
        {"body": 10, "spirit": 10, "insight": 10, "root": 10, "agility": 10, "fortune": 10},
        ensure_ascii=False,
    )
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', path_key='beast', realm_key=?, realm_layer=?, "
            "stamina=160, stamina_max=160, spirit_stones=5000, cultivation=3000000, "
            "max_hp=100000, initiative=100000, bloodline_stability=33, "
            "qualification_json=?, location_key=? "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (realm, layer, qualification, location, user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
            (user,),
        ).fetchone()[0]
        connection.execute(
            "INSERT OR REPLACE INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, "
            "status, attempt_count, first_clear_claimed, first_clear_key, created_at, updated_at) "
            "VALUES (?, 'story.mainline.xuantian', 12, 3, 'chapter.12.stage.3', 'claimed', 1, 1, ?, ?, ?)",
            (player_id, f"chapter.12.stage.3:{player_id}", "2026-10-11T00:00:00+00:00", "2026-10-11T00:00:00+00:00"),
        )
        connection.commit()


def test_the_beast_chapter_is_a_gated_l10_chain() -> None:
    definitions = {item.key: item for item in mainline_definitions(None, story_key=MAINLINE_STORY_KEY)}
    assert len(definitions) == 40
    assert definitions["chapter.12.stage.3"].next_stage_key == "chapter.13.stage.1"

    for previous, key in zip(BEAST_STAGES, BEAST_STAGES[1:]):
        assert definitions[previous].next_stage_key == key
    assert definitions[BEAST_STAGES[-1]].next_stage_key is None

    for key in BEAST_STAGES:
        stage = definitions[key]
        assert stage.required_realm == "nascent_soul"
        assert stage.required_layer == 10, f"{key} must sit on the realm's cap layer"
        assert len(stage.body.strip()) >= 80, f"{key} body is a title, not a stage"
        assert stage.objectives, f"{key} has no objective"
        assert stage.state_events, f"{key} must leave a story trail"
        assert stage.actions, f"{key} must tell the player what to send"
        assert stage.retry_message, f"{key} must say how to retry"
        assert "再次" in stage.retry_message or "再" in stage.retry_message


def test_every_beast_action_is_a_command_a_player_can_send(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = create_runtime(data_dir=tmp_path, adapters=("onebot.v11",))
        try:
            handlers = runtime.adapters.router._handlers
            stages = {
                item.key: item
                for item in mainline_definitions(None, story_key=MAINLINE_STORY_KEY)
            }
            for key in BEAST_STAGES:
                for action in stages[key].actions:
                    command = str(action["command"]).strip().lower()
                    argument = str(action.get("argument", "")).strip()
                    assert command in handlers, (
                        f"{key} tells the player to send {command!r}, which is not registered"
                    )
                    assert argument, f"{key} action {command!r} has no argument"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_the_gate_still_rejects_a_short_body_or_a_broken_chain(tmp_path: Path) -> None:
    short = _copy_content(tmp_path / "short")
    story_path = short / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "chapter.13.stage.2")
    stage["body"] = "只是一句标题。"
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="body is too short"):
        mainline_definitions(ContentBundle.load(short), story_key=MAINLINE_STORY_KEY)

    broken = _copy_content(tmp_path / "chain")
    story_path = broken / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "chapter.13.stage.1")
    stage["next_stage_key"] = "chapter.12.stage.1"
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="not consecutive"):
        mainline_definitions(ContentBundle.load(broken), story_key=MAINLINE_STORY_KEY)


def test_a_nascent_l10_player_clears_the_whole_beast_chapter(tmp_path: Path) -> None:
    content = _copy_content(tmp_path / "walk")
    _pin_beast_content(content)

    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("onebot.v11",))
        user = "beast-chapter-onebot"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch(
                "onebot.v11", _context(user, operation), command
            )

        try:
            assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
            # 寻仙问道 enters the cultivation path; without it the character has no
            # combat stats and every 万兽山 battle resolves as an instant loss.
            assert (await send("seek", "寻仙问道")).code == "SEEKING_STARTED"
            _stage_ready_player(runtime, user, realm="nascent_soul", layer=10)

            # 13.1 入山问脉 — 万兽山 is reachable only from 云舟渡口, and that
            # location additionally requires 妖界声望 200 or the 妖界引导 access
            # flag. Prove the no-route refusal first, then open the gate the way a
            # player must: 近郊 observation -> 阅读妖界史 -> 完成妖界引导.
            started = await send("s1-start", "开始主线 入山问脉")
            assert started.code == "MAINLINE_STARTED", started.message
            early = await send("s1-early", "领取主线奖励 入山问脉")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early.message

            no_route = await send("s1-gated", "前往 万兽山入口")
            assert no_route.code == "TRAVEL_ROUTE_INVALID", no_route.message

            assert (await send("gate-travel", "前往 近郊")).code == "TRAVEL_STARTED"
            clock.advance(seconds=40)
            assert (await send("gate-arrive", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("gate-explore", "开始探索 近郊采集")).code == "EXPLORATION_STARTED"
            clock.advance(minutes=15)
            assert (await send("gate-settle", "结算探索")).code == "EXPLORATION_SETTLED"
            assert (await send("gate-read", "阅读妖界史")).code == "BEAST_HISTORY_RECORDED"
            assert (await send("gate-intro", "完成妖界引导")).code == "BEAST_INTRO_COMPLETED"

            # 近郊 -> 青石镇 -> 云城 -> 云舟渡口 -> 万兽山入口
            assert (await send("t1", "前往 青石镇")).code == "TRAVEL_STARTED"
            clock.advance(seconds=10)
            assert (await send("t1-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("t2", "前往 云城")).code == "TRAVEL_STARTED"
            clock.advance(seconds=200)
            assert (await send("t2-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("t3", "前往 云舟渡口")).code == "TRAVEL_STARTED"
            clock.advance(seconds=70)
            assert (await send("t3-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("s1-travel", "前往 万兽山入口")).code == "TRAVEL_STARTED"
            clock.advance(seconds=310)
            assert (await send("s1-arrive", "结算移动")).code == "TRAVEL_COMPLETED"
            s1 = await send("s1-claim", "领取主线奖励 入山问脉")
            assert s1.code == "MAINLINE_REWARD_CLAIMED", s1.message
            assert s1.data["next_stage_key"] == "chapter.13.stage.2"

            # 13.2 循血猎兽 — a real 万兽山狩猎 settlement pays 兽血.
            # 万兽山 always battles; a real weapon one-shots the 7500 hp guardian
            # instead of a bare-handed round-cap loss.
            equip_damage_weapon(runtime, "onebot.v11", user, 50_000)
            assert (await send("s2-start", "开始主线 循血猎兽")).code == "MAINLINE_STARTED"
            explore = await send("s2-explore", "开始探索 万兽山狩猎")
            assert explore.code == "EXPLORATION_STARTED", explore.message
            clock.advance(minutes=20)
            settled = await send("s2-settle", "结算探索")
            assert settled.code == "EXPLORATION_SETTLED", settled.message
            assert settled.data["result"]["item.beast_blood"] >= 1, settled.data
            assert settled.data["battle_outcome"] == "won", settled.data
            s2 = await send("s2-claim", "领取主线奖励 循血猎兽")
            assert s2.code == "MAINLINE_REWARD_CLAIMED", s2.message
            assert s2.data["next_stage_key"] == "chapter.13.stage.3"

            # 13.3 守山定契 — the guardian fight closes the realm
            clock.advance(days=1)  # 万兽山狩猎 is limited to 2 runs per business day
            assert (await send("s3-start", "开始主线 守山定契")).code == "MAINLINE_STARTED"
            explore3 = await send("s3-explore", "开始探索 万兽山狩猎")
            assert explore3.code == "EXPLORATION_STARTED", explore3.message
            clock.advance(minutes=20)
            settled3 = await send("s3-settle", "结算探索")
            assert settled3.code == "EXPLORATION_SETTLED", settled3.message
            assert settled3.data.get("battle_outcome") == "won", settled3.data
            s3 = await send("s3-claim", "领取主线奖励 守山定契")
            assert s3.code == "MAINLINE_REWARD_CLAIMED", s3.message
            assert s3.data["next_stage_key"] is None

            replay = await send("s3-claim", "领取主线奖励 守山定契")
            assert replay.code == "MAINLINE_REWARD_CLAIMED", replay.message
            assert replay.data.get("idempotent_replay") is True
            assert replay.data["reward"] == s3.data["reward"]
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("realm", "layer"),
    [("nascent_soul", 9), ("golden_core", 3)],
)
def test_an_under_levelled_player_cannot_open_the_beast_chapter(
    tmp_path: Path, realm: str, layer: int
) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("onebot.v11",))
        user = f"beast-refused-{realm}-{layer}"

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch(
                "onebot.v11", _context(user, operation), command
            )

        try:
            assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
            _stage_ready_player(runtime, user, realm=realm, layer=layer)
            refused = await send("start-refused", "开始主线 入山问脉")
            assert refused.code == "MAINLINE_REQUIREMENT_MISSING", refused.message
        finally:
            await runtime.close()

    asyncio.run(run())
