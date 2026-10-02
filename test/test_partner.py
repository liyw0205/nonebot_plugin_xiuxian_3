from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        from datetime import timedelta

        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_player(runtime, adapter: str, user: str, dao_name: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user), f"开始修仙 {dao_name}")).ok
    assert (await runtime.dispatch(_context(adapter, user), "寻仙问道")).ok


def _promote(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )


def _assets(runtime, identities: tuple[tuple[str, str], ...]) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(
            connection.execute(
                "SELECT spirit_stones, stamina, energy, cultivation, total_cultivation, inventory_json, "
                "durability_json FROM players WHERE platform=? AND platform_user_id=?",
                identity,
            ).fetchone()
            for identity in identities
        )


def test_partner_lifecycle_cross_adapter_is_idempotent_and_asset_free() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11", "web"))
            await _create_player(runtime, "qq.official", "qq-a", "青玄")
            await _create_player(runtime, "onebot.v11", "ob-b", "白衡")
            _promote(runtime, "qq.official", "qq-a")
            _promote(runtime, "onebot.v11", "ob-b")
            identities = (("qq.official", "qq-a"), ("onebot.v11", "ob-b"))
            before = _assets(runtime, identities)

            invited = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "qq-a", "partner-invite"), "邀请结为道侣 白衡"
            )
            assert invited.code == "PARTNER_INVITED"
            assert "qq-a" not in invited.message and "ob-b" not in invited.message
            assert "qq-a" not in json.dumps(invited.data, ensure_ascii=False)
            replay = await runtime.dispatch(
                _context("qq.official", "qq-a", "partner-invite"), "邀请结为道侣 白衡"
            )
            assert replay.data["idempotent_replay"] is True
            accepted = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "ob-b", "partner-accept"),
                f"接受道侣邀请 {invited.data['relation_id']}",
            )
            assert accepted.code == "PARTNER_ACCEPTED"
            accepted_replay = await runtime.dispatch(
                _context("onebot.v11", "ob-b", "partner-accept"),
                f"接受道侣邀请 {invited.data['relation_id']}",
            )
            assert accepted_replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context("onebot.v11", "ob-b", "partner-accept"),
                "接受道侣邀请 different-relation",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            requested = await runtime.dispatch(
                _context("qq.official", "qq-a", "partner-dissolve-request"),
                f"申请解除道侣 {invited.data['relation_id']}",
            )
            assert requested.code == "PARTNER_DISSOLUTION_REQUESTED"
            rejected = await runtime.dispatch(
                _context("onebot.v11", "ob-b", "partner-dissolve-reject"),
                f"拒绝解除道侣 {invited.data['relation_id']}",
            )
            assert rejected.code == "PARTNER_DISSOLUTION_REJECTED"
            assert rejected.data["status"] == "active"
            requested_again = await runtime.dispatch(
                _context("onebot.v11", "ob-b", "partner-dissolve-request-again"),
                f"申请解除道侣 {invited.data['relation_id']}",
            )
            assert requested_again.code == "PARTNER_DISSOLUTION_REQUESTED"
            dissolved = await runtime.dispatch(
                _context("qq.official", "qq-a", "partner-dissolve-confirm"),
                f"确认解除道侣 {invited.data['relation_id']}",
            )
            assert dissolved.code == "PARTNER_DISSOLVED"
            assert dissolved.data["status"] == "dissolved"
            assert _assets(runtime, identities) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM partner_relations").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'social.%partner%'").fetchone()[0] == 6
            await runtime.close()

    asyncio.run(run())


def test_partner_expiry_and_pair_cooldown() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _create_player(runtime, "web", "a", "甲"); await _create_player(runtime, "web", "b", "乙")
            _promote(runtime, "web", "a"); _promote(runtime, "web", "b")
            invite = await runtime.dispatch(_context("web", "a", "invite-1"), "邀请结为道侣 乙")
            clock.advance(days=4)
            late = await runtime.dispatch(_context("web", "b", "accept-late"), f"接受道侣邀请 {invite.data['relation_id']}")
            assert late.code == "PARTNER_INVITATION_EXPIRED"
            invite2 = await runtime.dispatch(_context("web", "a", "invite-2"), "邀请结为道侣 乙")
            await runtime.dispatch(_context("web", "b", "accept-2"), f"接受道侣邀请 {invite2.data['relation_id']}")
            await runtime.dispatch(_context("web", "a", "request-2"), f"申请解除道侣 {invite2.data['relation_id']}")
            await runtime.dispatch(_context("web", "b", "confirm-2"), f"确认解除道侣 {invite2.data['relation_id']}")
            blocked = await runtime.dispatch(_context("web", "a", "invite-3"), "邀请结为道侣 乙")
            assert blocked.code == "PARTNER_BREAK_COOLDOWN"
            clock.advance(days=4)
            allowed = await runtime.dispatch(_context("web", "a", "invite-4"), "邀请结为道侣 乙")
            assert allowed.code == "PARTNER_INVITED"
            await runtime.close()

    asyncio.run(run())


def test_partner_content_controls_realm_requirement() -> None:
    async def run() -> None:
        with TemporaryDirectory() as content_dir:
            source = Path(__file__).resolve().parents[1] / "data"
            shutil.copytree(source, content_dir, dirs_exist_ok=True)
            social_path = Path(content_dir) / "社交" / "玩家互动.json"
            document = json.loads(social_path.read_text(encoding="utf-8"))
            next(record for record in document["records"] if record["key"] == "social.partner")["required_realm"] = "foundation"
            next(record for record in document["records"] if record["key"] == "social.partner")["required_layer"] = 1
            social_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            runtime = create_runtime(settings=XiuxianSettings.from_env(content_dir), adapters=("web",))
            await _create_player(runtime, "web", "a", "甲"); await _create_player(runtime, "web", "b", "乙")
            _promote(runtime, "web", "a"); _promote(runtime, "web", "b")
            result = await runtime.dispatch(_context("web", "a", "content-invite"), "邀请结为道侣 乙")
            assert result.code == "PARTNER_INVITED"
            await runtime.close()

    asyncio.run(run())


def test_partner_invites_are_unique_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for user, name in (("a", "甲"), ("b", "乙"), ("c", "丙")):
                await _create_player(runtime, "web", user, name)
                _promote(runtime, "web", user)
            results = await asyncio.gather(
                runtime.dispatch(_context("web", "a", "invite-a"), "邀请结为道侣 丙"),
                runtime.dispatch(_context("web", "b", "invite-b"), "邀请结为道侣 丙"),
            )
            assert sorted(result.code for result in results) == ["PARTNER_INVITED", "PARTNER_RELATION_CONFLICT"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM partner_relations WHERE status='invited'").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
