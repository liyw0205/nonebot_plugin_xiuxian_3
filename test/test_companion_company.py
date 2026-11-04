from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.interaction_content import (
    affinity_gain,
    companion_interaction_definition,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(user: str = "a") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user)


def _prepare(runtime, *, stamina: int = 100, affinity: int = 0, constitution: dict | None = None) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = int(
            connection.execute(
                "SELECT id FROM players WHERE platform_user_id='a'"
            ).fetchone()[0]
        )
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=3, "
            "stamina=?, stamina_max=100 WHERE id=?",
            (stamina, player_id),
        )
        connection.execute(
            "INSERT INTO companion_instances(instance_id, player_id, companion_key, kind, status, "
            "level, experience, affinity, stamina, deployed, snapshot_json, created_at, updated_at) "
            "VALUES ('ci-1', ?, 'beast.wood_rat', 'beast', 'active', 1, 0, ?, 100, 0, '{}', "
            "'2026-11-05T05:00:00+00:00', '2026-11-05T05:00:00+00:00')",
            (player_id, affinity),
        )
        if constitution is not None:
            connection.execute(
                "INSERT INTO constitution_profiles(profile_id, player_id, operation_id, "
                "constitution_key, status, selected_at, snapshot_json, created_at, updated_at) "
                "VALUES ('cp-1', ?, 'op-cp-1', 'constitution.beast_affinity', 'selected', "
                "'2026-11-05T05:00:00+00:00', ?, '2026-11-05T05:00:00+00:00', "
                "'2026-11-05T05:00:00+00:00')",
                (player_id, json.dumps({"effect": constitution}, ensure_ascii=False)),
            )
    return player_id


def _state(runtime, player_id: int) -> tuple[int, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        affinity = int(
            connection.execute(
                "SELECT affinity FROM companion_instances WHERE instance_id='ci-1'"
            ).fetchone()[0]
        )
        stamina = int(
            connection.execute("SELECT stamina FROM players WHERE id=?", (player_id,)).fetchone()[0]
        )
    return affinity, stamina


def test_interaction_content_matches_the_shipped_record() -> None:
    definition = companion_interaction_definition("灵兽相伴")
    assert definition.key == "interaction.companion.company"
    assert definition.base_affinity == 3
    assert definition.constitution_effect == "beast_affinity"
    assert definition.affinity_per_constitution_point == 1
    assert definition.affinity_cap == 100
    assert definition.stamina_cost == 10
    assert definition.daily_limit == 1
    assert definition.closed is False
    # Aliases resolve to the same record.
    assert companion_interaction_definition("相伴灵兽").key == definition.key


def test_constitution_bonus_applies_only_to_its_own_effect() -> None:
    definition = companion_interaction_definition("灵兽相伴")
    assert affinity_gain(definition, {"type": "beast_affinity", "value": 5}) == 8
    assert affinity_gain(definition, {"type": "max_hp_bp", "value": 300}) == 3
    assert affinity_gain(definition, None) == 3
    assert affinity_gain(definition, {}) == 3


def test_company_grants_affinity_once_a_day_and_spends_stamina() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "开始修仙")).ok
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "寻仙问道")).ok
                player_id = _prepare(runtime)

                first = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert first.ok, first.message
                assert first.code == "COMPANION_COMPANIED"
                assert _state(runtime, player_id) == (3, 90)

                second = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert second.ok is False
                assert second.code == "COMPANION_COMPANY_SPENT"
                assert _state(runtime, player_id) == (3, 90), "a refused attempt must not change state"

                # The next UTC day opens the interaction again.
                clock.value = clock.value + timedelta(days=1)
                third = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert third.ok, third.message
                assert _state(runtime, player_id) == (6, 80)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_beast_affinity_constitution_adds_its_bonus() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)
            )
            try:
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "开始修仙")).ok
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "寻仙问道")).ok
                player_id = _prepare(
                    runtime, constitution={"type": "beast_affinity", "value": 5}
                )
                granted = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert granted.ok, granted.message
                assert _state(runtime, player_id) == (8, 90)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_affinity_stops_at_the_configured_cap() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)
            )
            try:
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "开始修仙")).ok
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "寻仙问道")).ok
                player_id = _prepare(
                    runtime, affinity=99, constitution={"type": "beast_affinity", "value": 5}
                )
                capped = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert capped.ok, capped.message
                assert _state(runtime, player_id) == (100, 90)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_resting_and_broke_companions_are_refused() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)
            )
            try:
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "开始修仙")).ok
                assert (await runtime.adapters.dispatch("onebot.v11", _context(), "寻仙问道")).ok
                player_id = _prepare(runtime, stamina=5)
                poor = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert poor.ok is False
                assert poor.code == "COMPANION_COMPANY_INSUFFICIENT"
                assert _state(runtime, player_id) == (0, 5)

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=100 WHERE id=?", (player_id,)
                    )
                    connection.execute(
                        "UPDATE companion_instances SET status='resting' WHERE instance_id='ci-1'"
                    )
                resting = await runtime.adapters.dispatch("onebot.v11", _context(), "灵兽相伴 ci-1")
                assert resting.ok is False
                assert resting.code == "COMPANION_RESTING"
                assert _state(runtime, player_id) == (0, 100)
            finally:
                await runtime.close()

    asyncio.run(run())