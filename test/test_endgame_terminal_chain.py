from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.endgame_rules import recipe_roll_bp


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=operation, operation_id=operation)


async def _prepare_terminal_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=10,
                endgame_status='tribulation', location_key='dao.origin_gate', path_key='body',
                dao_fruit_progress=1000, ascension_merit=1000, world_merit=1000,
                tribulation_debt=0, qualification_json=?, inventory_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({"body": 2_000, "agility": 2_000}),
                json.dumps({"item.tribulation_token": 1}),
                adapter,
                user,
            ),
        )
        player_id = db.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        for index, trial_key in enumerate(
            ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice"), start=1
        ):
            db.execute(
                """
                INSERT INTO tribulation_trial_sessions(
                    session_id, player_id, operation_id, trial_key, status,
                    starts_at, ends_at, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', ?, ?)
                """,
                (
                    f"{user}-trial-{index}",
                    player_id,
                    f"{user}-trial-operation-{index}",
                    trial_key,
                    "2026-09-23T00:00:00+00:00",
                    "2026-09-23T00:30:00+00:00",
                    "2026-09-23T00:00:00+00:00",
                    "2026-09-23T00:30:00+00:00",
                ),
            )


def test_qq_and_onebot_terminal_recipe_to_ending_command_chain() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"terminal-{adapter}"
                await _prepare_terminal_player(runtime, adapter, user)
                certificate_operation = next(
                    f"{user}-certificate-{index}"
                    for index in range(1_000)
                    if recipe_roll_bp(f"{user}-certificate-{index}") < 8_000
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, certificate_operation),
                    "开始终局配方 飞升凭证",
                )
                assert started.code == "ENDGAME_RECIPE_STARTED"
                replay = await runtime.dispatch(
                    _ctx(adapter, user, certificate_operation),
                    "开始终局配方 recipe.ascension.certificate",
                )
                assert replay.data["idempotent_replay"] is True
                early = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-certificate-early"), "结算终局配方"
                )
                assert early.code == "ENDGAME_RECIPE_NOT_READY"
                clock.advance(minutes=11)
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-certificate-settle"), "结算终局配方"
                )
                assert settled.code == "ENDGAME_RECIPE_SETTLED"
                assert settled.data["success"] is True
                assert settled.data["rewards"] == {"item.ascension_certificate": 1}

                travel = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-sky-start"), "前往 天劫台"
                )
                assert travel.code == "TRAVEL_STARTED"
                clock.advance(minutes=31)
                arrived = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-sky-settle"), "结算移动"
                )
                assert arrived.code == "TRAVEL_COMPLETED"
                assert arrived.data["destination"] == "tribulation.sky_terrace"

                created = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-final-create"), "创建终局战"
                )
                assert created.code == "FINAL_BATTLE_CREATED"
                battle_id = created.data["battle_id"]
                started_battle = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-final-start"), f"开始终局战 {battle_id}"
                )
                if started_battle.code == "FINAL_BATTLE_CHOICE_REQUIRED":
                    settled_battle = await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-final-continue"),
                        f"选择终局战 继续 {battle_id}",
                    )
                else:
                    settled_battle = started_battle
                assert settled_battle.code == "FINAL_BATTLE_SETTLED"
                assert settled_battle.data["outcome"] == "won"
                assert settled_battle.data["debt_delta"] == 0

                ending = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-ending"), "选择结局 飞升"
                )
                assert ending.code == "ENDING_CHOSEN"
                assert ending.data["status"] == "ascended"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    status, location, inventory = db.execute(
                        "SELECT endgame_status, location_key, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert (status, location) == ("ascended", "ascension.heaven_path")
                assert json.loads(inventory)["item.title.ascended"] == 1
            await runtime.close()

    asyncio.run(run())
