"""Every non-void-spire enemy must be resolvable from content.

`enemy_definition` prefers a content record when it declares `combat_profile` and
otherwise falls back to the Python ``ENEMIES`` table (`combat/rules.py`).  Three
records used to sit in that gap — `enemy.iron_boar`, `enemy.beast_guardian` and
`enemy.tribulation_heaven` — so editing their `stats` in content was silently
ignored.  These tests pin the swap to content as value-for-value identical and
prove a content edit now actually reaches the battle snapshot.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from combat_fixtures import equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

ROOT = Path(__file__).parents[1]
ENEMY_FILE = Path("战斗/敌人.json")
CONTENTIZED = ("enemy.iron_boar", "enemy.beast_guardian", "enemy.tribulation_heaven")
COMPARED_FIELDS = (
    "max_hp",
    "attack",
    "initiative",
    "agility",
    "skill_key",
    "label",
    "location_key",
    "reward",
    "reward_refs",
    "random_pool",
    "required_realm",
    "required_layer",
)


def _copy_content(target: Path) -> Path:
    shutil.copytree(
        ROOT / "data",
        target,
        ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
    )
    return target


def _strip_profiles(content: Path) -> Path:
    """Reproduce the pre-change bundle: these three fall back to the code table."""

    path = content / ENEMY_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] in CONTENTIZED:
            record.pop("combat_profile", None)
            if record["key"] == "enemy.iron_boar":
                record["stats"].pop("agility", None)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return content


def test_every_non_void_spire_enemy_declares_a_combat_profile() -> None:
    document = json.loads((ROOT / "data" / ENEMY_FILE).read_text(encoding="utf-8"))
    code_owned = [
        record["key"]
        for record in document["records"]
        if not isinstance(record.get("combat_profile"), dict)
    ]
    # The twelve void-spire enemies are resolved from 特殊/虚空塔.json by their own
    # branch in enemy_definition(); nothing else may be left on the code table.
    assert [key for key in code_owned if not key.startswith("enemy.void_spire.")] == []
    assert len(code_owned) == 12


def test_contentizing_these_three_changed_no_combat_value() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    with tempfile.TemporaryDirectory() as tmp:
        before_dir = _strip_profiles(_copy_content(Path(tmp) / "before"))
        before = ContentBundle.load(before_dir)

        for key in ("enemy.iron_boar", "enemy.beast_guardian"):
            old = enemy_definition(key, content=before)
            new = enemy_definition(key, content=bundle)
            differences = [
                (field, getattr(old, field), getattr(new, field))
                for field in COMPARED_FIELDS
                if getattr(old, field) != getattr(new, field)
            ]
            assert differences == [], f"{key} changed when content took over: {differences}"

        # This one could not be resolved at all before (no profile, not in ENEMIES).
        try:
            enemy_definition("enemy.tribulation_heaven", content=before)
        except ValueError:
            pass
        else:  # pragma: no cover - would mean the record was already content-backed
            raise AssertionError("enemy.tribulation_heaven was expected to be code-less")

        trial = enemy_definition("enemy.tribulation_heaven", content=bundle)
        assert (trial.max_hp, trial.attack, trial.initiative, trial.agility) == (
            150000,
            5500,
            1600,
            650,
        )
        assert trial.skill_key == "skill.tribulation.thunder"
        assert trial.random_pool == "battle.enemy.tribulation_heaven"


def test_void_spire_enemies_still_resolve_from_tower_content() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    scout = enemy_definition("enemy.void_spire.scout", content=bundle)
    assert scout.max_hp > 0
    assert scout.key == "enemy.void_spire.scout"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 11, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def test_an_edited_enemy_stat_now_reaches_the_battle_snapshot() -> None:
    """Regression: a content edit must land in the frozen battle snapshot.

    Before these three declared `combat_profile`, editing `stats` did nothing and the
    fight used the Python table, which is exactly how chapter.13 was misdiagnosed.
    """

    with tempfile.TemporaryDirectory() as tmp:
        content = _copy_content(Path(tmp) / "data")
        enemy_path = content / ENEMY_FILE
        document = json.loads(enemy_path.read_text(encoding="utf-8"))
        for record in document["records"]:
            if record["key"] in {"enemy.beast_guardian", "enemy.beast_stalker"}:
                record["stats"] = {"hp": 1, "attack": 0, "initiative": 0, "agility": 0}
        enemy_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

        clock = _Clock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=("onebot.v11",))

        def context(operation: str) -> CommandContext:
            return CommandContext(adapter="onebot.v11", user_id="parity", operation_id=operation)

        async def run() -> None:
            assert (await runtime.adapters.dispatch("onebot.v11", context("create"), "开始修仙")).ok
            assert (await runtime.adapters.dispatch("onebot.v11", context("seek"), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', path_key='beast', "
                    "realm_key='nascent_soul', realm_layer=1, stamina=200, stamina_max=200, "
                    "spirit_stones=9000, max_hp=100000, initiative=100000, "
                    "bloodline_stability=33, location_key='beast.ten_thousand_hills', "
                    "intro_json=? WHERE platform='onebot.v11' AND platform_user_id='parity'",
                    (json.dumps({"flags": ["access.beast_ten_thousand_hills"]}),),
                )
                connection.commit()
            equip_damage_weapon(runtime, "onebot.v11", "parity", 50_000)

            started = await runtime.adapters.dispatch(
                "onebot.v11", context("explore"), "开始探索 万兽山狩猎"
            )
            assert started.code == "EXPLORATION_STARTED", started.message
            clock.advance(minutes=20)
            settled = await runtime.adapters.dispatch("onebot.v11", context("settle"), "结算探索")
            assert settled.code == "EXPLORATION_SETTLED", settled.message
            assert settled.data["battle_outcome"] == "won", settled.data

            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM battle_sessions ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()[0]
                )
            enemy = snapshot["enemy"]
            assert enemy["max_hp"] == 1, enemy
            assert enemy["attack"] == 0, enemy

            await runtime.close()

        asyncio.run(run())
