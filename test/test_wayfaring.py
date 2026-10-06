from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - optional billing extra
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings


TEST_NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def _context(
    user_id: str,
    request_id: str,
    *,
    operation_id: str = "",
    adapter: str = "web",
) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _signed_receipt(private_key: object, payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{encode(canonical)}.{encode(private_key.sign(canonical))}"


def _insert_source_operations(runtime, user_id: str, names: list[str]) -> None:
    now = TEST_NOW.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform_user_id = ?", (user_id,)
        ).fetchone()[0]
        for index, name in enumerate(names):
            operation_id = f"source-{index}-{name}"
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, name, player_id, f"hash-{index}", json.dumps({}), now),
            )


def test_wayfaring_start_status_caps_and_free_claim_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: TEST_NOW)
            user = "wayfaring-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            started = await runtime.dispatch(_context(user, "start"), "开始行卷")
            assert started.code == "WAYFARING_STARTED"
            replay = await runtime.dispatch(
                _context(user, "start-replay", operation_id=started.operation_id or ""),
                "开始行卷",
            )
            assert replay.code == "WAYFARING_STARTED"
            assert replay.data["idempotent_replay"] is True

            _insert_source_operations(
                runtime,
                user,
                ["routine.checkin.daily"] * 6 + ["production.complete"] * 4,
            )
            status = await runtime.dispatch(_context(user, "status"), "问道行卷")
            assert status.code == "WAYFARING_STATUS"
            assert status.data["daily_points"] == 100
            assert status.data["total_points"] == 100
            assert status.data["current_level"] == 1

            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="claim-free-1"),
                "领取行卷 1",
            )
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED"
            duplicate = await runtime.dispatch(
                _context(user, "claim-duplicate"),
                "领取行卷 1",
            )
            assert duplicate.code == "WAYFARING_ALREADY_CLAIMED"
            replay_claim = await runtime.dispatch(
                _context(user, "claim-replay", operation_id="claim-free-1"),
                "领取行卷 1",
            )
            assert replay_claim.code == "WAYFARING_LEVEL_CLAIMED"
            assert replay_claim.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_wayfaring_paid_track_requires_monthly_contract_without_asset_change() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: TEST_NOW)
            user = "wayfaring-paid-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "start"), "开始行卷")).ok
            _insert_source_operations(runtime, user, ["production.complete"] * 4)
            assert (await runtime.dispatch(_context(user, "status"), "问道行卷")).data["current_level"] == 1
            before = sqlite3.connect(runtime.settings.database_path).execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?", (user,)
            ).fetchone()
            result = await runtime.dispatch(_context(user, "paid"), "领取行卷 1 付费")
            assert result.code == "WAYFARING_PAID_LOCKED"
            after = sqlite3.connect(runtime.settings.database_path).execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?", (user,)
            ).fetchone()
            assert before == after
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_wayfaring_titles_settle_atomically_and_replay_across_adapters(adapter: str) -> None:
    async def run() -> None:
        if Ed25519PrivateKey is None:
            pytest.skip("cryptography billing extra is not installed")
        clock = MutableClock(TEST_NOW)
        private_key = Ed25519PrivateKey.generate()
        public_key = base64.urlsafe_b64encode(
            private_key.public_key().public_bytes_raw()
        ).decode("ascii").rstrip("=")
        with TemporaryDirectory() as data_dir:
            settings = XiuxianSettings(
                data_dir=Path(data_dir), billing_public_key=public_key
            )
            runtime = create_runtime(settings=settings, clock=clock)
            free_user = f"wayfaring-free-{adapter}"
            assert (await runtime.dispatch(
                _context(free_user, "free-create", adapter=adapter), "开始修仙"
            )).ok
            assert (await runtime.dispatch(
                _context(free_user, "free-start", adapter=adapter), "开始行卷"
            )).ok
            for day in range(28):
                checkin = await runtime.dispatch(
                    _context(free_user, f"free-checkin-{day}", adapter=adapter),
                    "道历问安",
                )
                assert checkin.ok, (adapter, checkin.code, checkin.message)
                if day < 27:
                    clock.advance(days=1)
            free_status = await runtime.dispatch(
                _context(free_user, "free-status", adapter=adapter), "问道行卷"
            )
            assert free_status.data["current_level"] == 7

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_wayfaring_claim BEFORE INSERT ON operations
                    WHEN NEW.operation_name = 'pass.wayfaring.claim'
                    BEGIN SELECT RAISE(ABORT, 'injected operation failure'); END
                    """
                )
            failed = await runtime.dispatch(
                _context(
                    free_user,
                    "free-claim-failed",
                    operation_id="wayfaring-free-claim",
                    adapter=adapter,
                ),
                "领取行卷 7",
            )
            assert failed.code == "PERSISTENCE_ERROR"
            assert failed.retryable is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, free_user),
                ).fetchone()[0]
                claim_state = connection.execute(
                    "SELECT claimed_free_json FROM wayfaring_passes WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0]
                assert json.loads(claim_state) == []
                assert connection.execute(
                    "SELECT COUNT(*) FROM wayfaring_claims WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM honor_titles WHERE player_id = ? AND title_key = ?",
                    (player_id, "title.wayfaring.pathfinder"),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = ?",
                    ("wayfaring-free-claim",),
                ).fetchone()[0] == 0
                connection.execute("DROP TRIGGER fail_wayfaring_claim")

            free_claim = await runtime.dispatch(
                _context(
                    free_user,
                    "free-claim-retry",
                    operation_id="wayfaring-free-claim",
                    adapter=adapter,
                ),
                "领取行卷 7",
            )
            assert free_claim.code == "WAYFARING_LEVEL_CLAIMED"
            assert free_claim.data["reward"]["title.wayfaring.pathfinder"] == 1
            assert "称号「行路先行」" in free_claim.message
            honor_status = await runtime.dispatch(
                _context(free_user, "free-honor-status", adapter=adapter), "功业录"
            )
            title = next(
                item for item in honor_status.data["titles"]
                if item["title_key"] == "title.wayfaring.pathfinder"
            )
            assert title["acquired"] is True

            await runtime.close()
            runtime = create_runtime(settings=settings, clock=clock)
            free_replay = await runtime.dispatch(
                _context(
                    free_user,
                    "free-claim-replay",
                    operation_id="wayfaring-free-claim",
                    adapter=adapter,
                ),
                "领取行卷 7",
            )
            assert free_replay.code == "WAYFARING_LEVEL_CLAIMED"
            assert free_replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(
                    free_user,
                    "free-claim-conflict",
                    operation_id="wayfaring-free-claim",
                    adapter=adapter,
                ),
                "领取行卷 7 付费",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            paid_user = f"wayfaring-paid-{adapter}"
            assert (await runtime.dispatch(
                _context(paid_user, "paid-create", adapter=adapter), "开始修仙"
            )).ok
            assert (await runtime.dispatch(
                _context(paid_user, "paid-start", adapter=adapter), "开始行卷"
            )).ok
            receipt = _signed_receipt(
                private_key,
                {
                    "receipt_id": f"wayfaring-monthly-{adapter}",
                    "subject": f"{adapter}:{paid_user}",
                    "contract_key": "dao_contract.monthly",
                    "amount": 600,
                    "currency": "spirit_stones",
                    "issued_at": clock.value.isoformat(),
                },
            )
            activated = await runtime.dispatch(
                _context(paid_user, "paid-contract", operation_id="paid-contract", adapter=adapter),
                f"激活道契 {receipt}",
            )
            assert activated.code == "DAO_CONTRACT_ACTIVATED"
            for day in range(4):
                checkin = await runtime.dispatch(
                    _context(paid_user, f"paid-checkin-{day}", adapter=adapter),
                    "道历问安",
                )
                assert checkin.ok, (adapter, checkin.code, checkin.message)
                if day < 3:
                    clock.advance(days=1)
            paid_status = await runtime.dispatch(
                _context(paid_user, "paid-status", adapter=adapter), "问道行卷"
            )
            assert paid_status.data["current_level"] == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER fail_paid_wayfaring_claim BEFORE INSERT ON operations
                    WHEN NEW.operation_name = 'pass.wayfaring.claim'
                    BEGIN SELECT RAISE(ABORT, 'injected operation failure'); END
                    """
                )
            paid_failed = await runtime.dispatch(
                _context(
                    paid_user,
                    "paid-claim-failed",
                    operation_id="wayfaring-paid-claim",
                    adapter=adapter,
                ),
                "领取行卷 1 付费",
            )
            assert paid_failed.code == "PERSISTENCE_ERROR"
            assert paid_failed.retryable is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, paid_user),
                ).fetchone()[0]
                pass_state = connection.execute(
                    "SELECT claimed_paid_json FROM wayfaring_passes WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0]
                assert json.loads(pass_state) == []
                assert connection.execute(
                    "SELECT COUNT(*) FROM wayfaring_claims WHERE player_id = ?",
                    (player_id,),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM honor_titles WHERE player_id = ? AND title_key = ?",
                    (player_id, "title.wayfaring.pathfinder"),
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id = ?",
                    ("wayfaring-paid-claim",),
                ).fetchone()[0] == 0
                connection.execute("DROP TRIGGER fail_paid_wayfaring_claim")

            paid_claim = await runtime.dispatch(
                _context(
                    paid_user,
                    "paid-claim-retry",
                    operation_id="wayfaring-paid-claim",
                    adapter=adapter,
                ),
                "领取行卷 1 付费",
            )
            assert paid_claim.code == "WAYFARING_LEVEL_CLAIMED"
            assert paid_claim.data["reward"]["title.wayfaring.pathfinder"] == 1
            assert "称号「行路先行」" in paid_claim.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, paid_user),
                ).fetchone()[0]
                assert connection.execute(
                    "SELECT COUNT(*) FROM honor_titles WHERE player_id = ? AND title_key = ?",
                    (player_id, "title.wayfaring.pathfinder"),
                ).fetchone()[0] == 1

            await runtime.close()
            runtime = create_runtime(settings=settings, clock=clock)
            paid_replay = await runtime.dispatch(
                _context(
                    paid_user,
                    "paid-claim-replay",
                    operation_id="wayfaring-paid-claim",
                    adapter=adapter,
                ),
                "领取行卷 1 付费",
            )
            assert paid_replay.code == "WAYFARING_LEVEL_CLAIMED"
            assert paid_replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM honor_titles WHERE player_id = ? AND title_key = ?",
                    (player_id, "title.wayfaring.pathfinder"),
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
