"""Content contract for the data-backed honor titles and dao contracts."""

from __future__ import annotations

import asyncio
import base64
import copy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - optional billing extra
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.content import (
    ContentBundle,
    ContentError,
    bundled_content,
)
from nonebot_plugin_xiuxian_3.xiuxian.routine import repository as routine_repository
from nonebot_plugin_xiuxian_3.xiuxian.routine import rules as routine_rules
from nonebot_plugin_xiuxian_3.xiuxian.routine import use_cases as routine_use_cases
from nonebot_plugin_xiuxian_3.xiuxian.routine.routine_content import (
    dao_contract_definitions,
    honor_title_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.routine.rules import (
    DAO_CONTRACTS,
    HONOR_TITLES,
    dao_contract,
    honor_title,
)
from test_routine import MutableClock, _context, _enter_mortal, _signed_receipt

TITLE_FILE = "道历/道号.json"
CONTRACT_FILE = "道历/道契.json"
SHIPPED_TITLES = (
    "title.first_seeking",
    "title.town_helper",
    "title.mist_watcher",
    "title.dispatch_helper",
    "title.first_tower_clear",
    "title.three_realms_tower.domain_guardian",
    "title.season.final_heaven.ascension",
    "title.season.final_heaven.dao",
    "title.season.final_heaven.cooperation",
    "title.void_spire.witness",
    "title.void_spire.origin",
    "title.void_spire.ascension",
    "title.wayfaring.pathfinder",
    "title.wayfaring.trailblazer",
    "title.wayfaring.seeker",
    "title.wayfaring.wayfarer",
    "title.wayfaring.licensed",
)


def _replace_record(
    content: ContentBundle, kind: str, record_key: str, **changes
) -> ContentBundle:
    records = dict(content._records)
    row = copy.deepcopy(dict(records[kind, record_key]))
    row.update(changes)
    records[kind, record_key] = row
    return replace(content, _records=records)


def test_title_and_contract_content_matches_the_shipped_tables() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    titles = honor_title_definitions(bundle)
    contracts = dao_contract_definitions(bundle)

    assert tuple(title.key for title in titles) == SHIPPED_TITLES
    assert titles == HONOR_TITLES
    assert contracts == DAO_CONTRACTS

    first = honor_title("title.first_seeking")
    assert (first.label, first.source_event, first.hint) == (
        "初入道途",
        "player.start_seeking",
        "首次寻仙问道",
    )
    assert first.closed is False

    wayfaring = honor_title("title.wayfaring.licensed")
    assert wayfaring.source_event is None
    assert wayfaring.hint

    weekly = dao_contract("dao_contract.weekly")
    assert weekly.duration_days == 7
    assert weekly.price == 180
    assert weekly.daily_reward_map() == {"spirit_stones": 35, "energy": 3}
    assert weekly.activation_reward_map() == {"item.ticket.fate_basic": 2}
    assert weekly.reputation_every_days is None

    monthly = dao_contract("dao_contract.monthly")
    assert monthly.reputation_every_days == 7
    assert monthly.reputation_reward == 3
    assert monthly.activation_reward_map() == {"item.cosmetic.dao_name_frame": 1}
    assert monthly.closed is False


@pytest.mark.parametrize(
    "kind,record_key,changes",
    [
        ("honor_title", "title.first_seeking", {"key": "titlex.bad"}),
        ("honor_title", "title.first_seeking", {"label": " "}),
        ("honor_title", "title.first_seeking", {"hint": ""}),
        ("honor_title", "title.first_seeking", {"source_event": ""}),
        ("honor_title", "title.first_seeking", {"status": "paused"}),
        ("honor_title", "title.first_seeking", {"unexpected": 1}),
        ("honor_title", "title.first_seeking", {"status": "active", "key": "title.town_helper"}),
        ("dao_contract", "dao_contract.daily", {"key": "contractx.bad"}),
        ("dao_contract", "dao_contract.daily", {"label": " "}),
        ("dao_contract", "dao_contract.daily", {"duration_days": 0}),
        ("dao_contract", "dao_contract.daily", {"duration_days": True}),
        ("dao_contract", "dao_contract.daily", {"price": -1}),
        ("dao_contract", "dao_contract.daily", {"daily_reward": {}}),
        ("dao_contract", "dao_contract.daily", {"daily_reward": {"energy": 0}}),
        ("dao_contract", "dao_contract.daily", {"daily_reward": {"energy": True}}),
        (
            "dao_contract",
            "dao_contract.daily",
            {"reputation_reward": 3},
        ),
        ("dao_contract", "dao_contract.daily", {"status": "paused"}),
        (
            "dao_contract",
            "dao_contract.daily",
            {"status": "active", "key": "dao_contract.weekly"},
        ),
    ],
)
def test_routine_content_rejects_invalid_records(
    kind: str, record_key: str, changes: dict
) -> None:
    content = _replace_record(bundled_content(), kind, record_key, **changes)
    with pytest.raises(ContentError):
        if kind == "honor_title":
            honor_title_definitions(content)
        else:
            dao_contract_definitions(content)


@pytest.mark.parametrize("kind", ["honor_title", "dao_contract"])
def test_routine_content_requires_at_least_one_record(kind: str) -> None:
    content = bundled_content()
    records = {
        identity: row for identity, row in content._records.items() if identity[0] != kind
    }
    with pytest.raises(ContentError, match="missing"):
        if kind == "honor_title":
            honor_title_definitions(replace(content, _records=records))
        else:
            dao_contract_definitions(replace(content, _records=records))


def test_closed_and_locked_rows_follow_the_achievement_contract() -> None:
    bundle = bundled_content()

    closed = honor_title_definitions(
        _replace_record(bundle, "honor_title", "title.town_helper", status="closed")
    )
    assert tuple(title.key for title in closed) == SHIPPED_TITLES
    assert [title.key for title in closed if title.closed] == ["title.town_helper"]

    locked = honor_title_definitions(
        _replace_record(bundle, "honor_title", "title.town_helper", status="locked")
    )
    assert tuple(title.key for title in locked) == tuple(
        key for key in SHIPPED_TITLES if key != "title.town_helper"
    )

    closed_contracts = dao_contract_definitions(
        _replace_record(bundle, "dao_contract", "dao_contract.weekly", status="closed")
    )
    assert [contract.key for contract in closed_contracts if contract.closed] == [
        "dao_contract.weekly"
    ]


def test_honor_status_shows_the_acquisition_hint() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "routine-title-hint"
            await _enter_mortal(runtime, user)

            status = await runtime.dispatch(_context(user, "honor-status"), "功业录")
            titles = status.data["titles"]
            assert titles[0]["acquired"] is True
            assert titles[0]["hint"] == "首次寻仙问道"
            assert "**1. 初入道途**：已获得" in status.message
            assert "首次寻仙问道（" not in status.message

            second = titles[1]
            assert second["acquired"] is False
            assert second["hint"] == "累计三次道历问安"
            assert "**2. 城镇助行者**：未获得（累计三次道历问安）" in status.message
            await runtime.close()

    asyncio.run(run())


def test_closed_dao_contract_refuses_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        if Ed25519PrivateKey is None:
            pytest.skip("cryptography billing extra is not installed")
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        private_key = Ed25519PrivateKey.generate()
        public_key = base64.urlsafe_b64encode(
            private_key.public_key().public_bytes_raw()
        ).decode("ascii").rstrip("=")
        with TemporaryDirectory() as data_dir:
            settings = XiuxianSettings(
                data_dir=Path(data_dir), billing_public_key=public_key
            )
            runtime = create_runtime(settings=settings, clock=clock)
            user = "routine-closed-contract"
            await _enter_mortal(runtime, user)
            receipt = _signed_receipt(
                private_key,
                {
                    "receipt_id": "receipt-closed-1",
                    "subject": f"web:{user}",
                    "contract_key": "dao_contract.weekly",
                    "amount": 180,
                    "currency": "spirit_stones",
                    "issued_at": clock.value.isoformat(),
                },
            )
            closed = tuple(
                replace(definition, closed=True)
                if definition.key == "dao_contract.weekly"
                else definition
                for definition in DAO_CONTRACTS
            )
            monkeypatch.setattr(routine_rules, "DAO_CONTRACTS", closed)
            monkeypatch.setattr(routine_use_cases, "DAO_CONTRACTS", closed)

            activated = await runtime.dispatch(
                _context(user, "activate", operation_id="closed-contract"),
                f"激活道契 {receipt}",
            )
            assert activated.code == "CONTENT_CLOSED", activated
            assert activated.message == "这类道契暂未开放，凭证未使用，未发放任何权益。"
            status = await runtime.dispatch(_context(user, "status"), "我的道契")
            assert status.data["contracts"] == []
            await runtime.close()

    asyncio.run(run())
