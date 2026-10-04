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
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.service_rules import service_definitions, service_reward
from test_livelihood import MutableClock, _onebot_event, _qq_event


SERVICE_KEY = "service.gather_help"


def _content(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    return data_dir


def _edit_service(data_dir: Path, change) -> None:
    path = data_dir / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in document["records"] if item.get("key") == SERVICE_KEY)
    change(row)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


async def _prepare(runtime, user: str) -> int:
    assert (await runtime.dispatch(_context(user, f"create-{user}"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, f"seek-{user}"), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT id FROM players WHERE platform='web' AND platform_user_id=?", (user,)
        ).fetchone()[0]


def _grant_service_reputation(runtime, player_id: int, amount: int = 10) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, '{}', ?, ?) "
            "ON CONFLICT(player_id) DO UPDATE SET service_reputation=excluded.service_reputation, "
            "updated_at=excluded.updated_at",
            (player_id, amount, datetime.now(timezone.utc).isoformat()),
        )


def test_service_rules_use_content_and_reject_bad_references(tmp_path: Path) -> None:
    data_dir = _content(tmp_path)
    content = ContentBundle.load(data_dir)
    definitions = service_definitions(content)
    assert definitions[SERVICE_KEY].provider_stamina == 3
    assert definitions[SERVICE_KEY].publisher_outputs == {"item.herb.blood_grass": 1}
    assert definitions["service.cook_meal"].default_reward_stones == 20
    assert service_reward(definitions["service.cook_meal"]) == 20

    _edit_service(
        data_dir,
        lambda row: row["publisher_outputs"].update({"item.unknown": 1}),
    )
    with pytest.raises(ContentError, match="unknown item"):
        service_definitions(ContentBundle.load(data_dir))


def test_service_snapshot_freezes_content_and_settlement_replays_after_restart(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_service(
            data_dir,
            lambda row: row.update(
                aliases=["采药帮工"],
                publisher_outputs={"item.herb.blood_grass": 2},
                failure_stamina_refund=2,
                duration_seconds=3600,
            ),
        )
        _edit_service(data_dir, lambda row: row["reward"].update(amount=27))
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        publisher_id = await _prepare(runtime, "service-publisher")
        provider_id = await _prepare(runtime, "service-provider")
        _grant_service_reputation(runtime, provider_id)

        published = await runtime.dispatch(
            _context("service-publisher", "publish"), "发布服务 采药帮工"
        )
        assert published.code == "SERVICE_PUBLISHED"
        order_id = published.data["order_id"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = json.loads(
                connection.execute(
                    "SELECT snapshot_json FROM livelihood_service_orders WHERE order_id=?", (order_id,)
                ).fetchone()[0]
            )
        assert snapshot["publisher_outputs"] == {"item.herb.blood_grass": 2}
        assert snapshot["service_description"] == "协助初学者熟悉近郊采集，可获得少量报酬。"
        accepted = await runtime.dispatch(
            _context("service-provider", "accept"), f"接取服务 {order_id}"
        )
        assert accepted.code == "SERVICE_ACCEPTED"
        await runtime.close()

        _edit_service(
            data_dir,
            lambda row: row.update(
                publisher_outputs={"item.herb.blood_grass": 9}, duration_seconds=10
            ),
        )
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        settled = await runtime.dispatch(
            _context("service-provider", "settle"), f"结算服务 {order_id}"
        )
        assert settled.code == "SERVICE_SETTLED"
        assert settled.data["provider_payment"] == 26
        assert settled.data["outputs"] == {"item.herb.blood_grass": 2}
        replay = await runtime.dispatch(
            _context("service-provider", "settle"), f"结算服务 {order_id}"
        )
        assert replay.data == {**settled.data, "idempotent_replay": True}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            publisher = connection.execute(
                "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (publisher_id,)
            ).fetchone()
            provider = connection.execute(
                "SELECT spirit_stones, stamina FROM players WHERE id=?", (provider_id,)
            ).fetchone()
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='settle'"
            ).fetchone()[0]
        assert publisher[0] == 73
        assert json.loads(publisher[1])["item.herb.blood_grass"] == 5
        assert provider == (126, 27)
        assert operation_count == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_service_publish_original_name_replays_after_content_rename_and_close(
    tmp_path: Path, kind: str,
) -> None:
    pytest.importorskip("nonebot")

    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_service(data_dir, lambda row: row.update(aliases=["采药帮工"]))
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        adapter = "onebot.v11" if kind == "onebot" else "qq.official"
        publisher = "1001" if kind == "onebot" else "service-history-publisher"

        def event(text: str, message_id: int):
            if kind == "onebot":
                return _onebot_event(text, message_id, user_id=1001, group_id=2002)
            return _qq_event(text, f"service-history-{message_id}", member_openid=publisher, group_openid="qq-group")

        async def send(text: str, message_id: int):
            from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
            from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

            raw = event(text, message_id)
            normalized = normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        assert (await send("开始修仙", 8200)).ok
        assert (await send("寻仙问道", 8201)).ok
        published = await send("发布服务 采药帮工 15", 8202)
        assert published.code == "SERVICE_PUBLISHED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            before = connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, publisher),
            ).fetchone()[0]
            order_count = connection.execute(
                "SELECT COUNT(*) FROM livelihood_service_orders WHERE publish_operation_id=?",
                (published.operation_id,),
            ).fetchone()[0]
        assert before == 85
        assert order_count == 1
        await runtime.close()

        _edit_service(
            data_dir,
            lambda row: row.update(name="采集新约", aliases=[], status="locked"),
        )
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        replay = await send("发布服务 采药帮工 15", 8202)
        assert replay.data == {**published.data, "idempotent_replay": True}
        assert "教学采集协助" in replay.message
        conflict = await send("发布服务 采集新约 15", 8202)
        assert conflict.code == "OPERATION_CONFLICT"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, publisher),
            ).fetchone()[0]
            order_count = connection.execute(
                "SELECT COUNT(*) FROM livelihood_service_orders WHERE publish_operation_id=?",
                (published.operation_id,),
            ).fetchone()[0]
        assert after == before
        assert order_count == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
@pytest.mark.parametrize("result_json", ["{", "[]", '{"status":"published"}'])
def test_service_publish_replay_rejects_corrupt_operation_without_writing(
    tmp_path: Path, kind: str, result_json: str,
) -> None:
    pytest.importorskip("nonebot")

    async def run() -> None:
        data_dir = _content(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        adapter = "onebot.v11" if kind == "onebot" else "qq.official"
        publisher = "1001" if kind == "onebot" else "service-corrupt-publisher"

        def event(text: str, message_id: int):
            if kind == "onebot":
                return _onebot_event(text, message_id, user_id=1001, group_id=2002)
            return _qq_event(text, f"service-corrupt-{message_id}", member_openid=publisher, group_openid="qq-group")

        async def send(text: str, message_id: int):
            from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
            from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

            raw = event(text, message_id)
            normalized = normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        assert (await send("开始修仙", 8300)).ok
        assert (await send("寻仙问道", 8301)).ok
        published = await send("发布服务 教学采集协助", 8302)
        assert published.code == "SERVICE_PUBLISHED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                (result_json, published.operation_id),
            )
            before = connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, publisher),
            ).fetchone()[0]
        replay = await send("发布服务 教学采集协助", 8302)
        assert replay.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, publisher),
            ).fetchone()[0]
            order_count = connection.execute(
                "SELECT COUNT(*) FROM livelihood_service_orders WHERE publish_operation_id=?",
                (published.operation_id,),
            ).fetchone()[0]
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                (published.operation_id,),
            ).fetchone()[0]
        assert after == before == 85
        assert order_count == 1
        assert operation_count == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_service_settlement_rejects_corrupt_snapshot_and_recovers(
    tmp_path: Path, kind: str,
) -> None:
    pytest.importorskip("nonebot")

    async def run() -> None:
        data_dir = _content(tmp_path)
        runtime = create_runtime(data_dir=data_dir)
        adapter = "onebot.v11" if kind == "onebot" else "qq.official"
        publisher = "1001" if kind == "onebot" else "service-snapshot-publisher"
        provider = "1002" if kind == "onebot" else "service-snapshot-provider"

        def event(text: str, message_id: int, user: str):
            if kind == "onebot":
                return _onebot_event(text, message_id, user_id=int(user), group_id=2002)
            return _qq_event(
                text,
                f"service-snapshot-{message_id}",
                member_openid=user,
                group_openid="qq-group",
            )

        async def send(text: str, message_id: int, user: str):
            from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
            from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

            raw = event(text, message_id, user)
            normalized = normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        for user, base in ((publisher, 8400), (provider, 8410)):
            assert (await send("开始修仙", base, user)).ok
            assert (await send("寻仙问道", base + 1, user)).ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            provider_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, provider),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, '{}', 10, ?) ON CONFLICT(player_id) DO UPDATE SET service_reputation=10",
                (provider_id, datetime.now(timezone.utc).isoformat()),
            )
        published = await send("发布服务 教学采集协助", 8420, publisher)
        assert published.code == "SERVICE_PUBLISHED"
        order_id = published.data["order_id"]
        accepted = await send(f"接取服务 {order_id}", 8421, provider)
        assert accepted.code == "SERVICE_ACCEPTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = connection.execute(
                "SELECT snapshot_json FROM livelihood_service_orders WHERE order_id=?",
                (order_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE livelihood_service_orders SET snapshot_json='{' WHERE order_id=?",
                (order_id,),
            )
            before = connection.execute(
                "SELECT p.spirit_stones, p.stamina, p.inventory_json, o.status "
                "FROM players p JOIN livelihood_service_orders o ON o.provider_id=p.id "
                "WHERE p.platform=? AND p.platform_user_id=? AND o.order_id=?",
                (adapter, provider, order_id),
            ).fetchone()
        failed = await send(f"结算服务 {order_id}", 8422, provider)
        assert failed.code == "SERVICE_ORDER_CONFLICT"
        settle_operation_id = "8422" if kind == "onebot" else "service-snapshot-8422"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT p.spirit_stones, p.stamina, p.inventory_json, o.status "
                "FROM players p JOIN livelihood_service_orders o ON o.provider_id=p.id "
                "WHERE p.platform=? AND p.platform_user_id=? AND o.order_id=?",
                (adapter, provider, order_id),
            ).fetchone()
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (settle_operation_id,)
            ).fetchone()[0] == 0
            connection.execute(
                "UPDATE livelihood_service_orders SET snapshot_json=? WHERE order_id=?",
                (snapshot, order_id),
            )
        assert after == before
        settled = await send(f"结算服务 {order_id}", 8422, provider)
        assert settled.code == "SERVICE_SETTLED"
        replay = await send(f"结算服务 {order_id}", 8422, provider)
        assert replay.data["idempotent_replay"] is True
        await runtime.close()

    asyncio.run(run())


def test_service_settlement_failure_rolls_back_and_retries(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        publisher_id = await _prepare(runtime, "failure-publisher")
        provider_id = await _prepare(runtime, "failure-provider")
        _grant_service_reputation(runtime, provider_id)
        published = await runtime.dispatch(
            _context("failure-publisher", "publish"), "发布服务 教学采集协助"
        )
        order_id = published.data["order_id"]
        assert (await runtime.dispatch(
            _context("failure-provider", "accept"), f"接取服务 {order_id}"
        )).code == "SERVICE_ACCEPTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET location_key='xuantian.outskirts' WHERE id=?", (provider_id,))
            before = connection.execute(
                "SELECT spirit_stones, stamina, inventory_json FROM players WHERE id=?", (provider_id,)
            ).fetchone()
            connection.execute(
                "CREATE TRIGGER fail_service_operation BEFORE INSERT ON operations "
                "WHEN NEW.operation_name='livelihood.settle_service' BEGIN "
                "SELECT RAISE(ABORT, 'injected service failure'); END"
            )
        failed = await runtime.dispatch(
            _context("failure-provider", "settle-retry"), f"结算服务 {order_id}"
        )
        assert failed.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT status FROM livelihood_service_orders WHERE order_id=?", (order_id,)
            ).fetchone()[0] == "accepted"
            assert connection.execute(
                "SELECT spirit_stones, stamina, inventory_json FROM players WHERE id=?", (provider_id,)
            ).fetchone() == before
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='settle-retry'"
            ).fetchone()[0] == 0
            connection.execute("DROP TRIGGER fail_service_operation")
        settled = await runtime.dispatch(
            _context("failure-provider", "settle-retry"), f"结算服务 {order_id}"
        )
        assert settled.code == "SERVICE_FAILED"
        assert settled.data["publisher_refund"] == 12
        assert settled.data["stamina_refund"] == 1
        replay = await runtime.dispatch(
            _context("failure-provider", "settle-retry"), f"结算服务 {order_id}"
        )
        assert replay.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT spirit_stones, stamina FROM players WHERE id=?", (publisher_id,)
            ).fetchone() == (97, 30)
        await runtime.close()

    asyncio.run(run())


def test_expired_service_refund_is_an_idempotent_operation(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _content(tmp_path)
        _edit_service(data_dir, lambda row: row.update(duration_seconds=1))
        clock = MutableClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await _prepare(runtime, "expiry-publisher")
        provider_id = await _prepare(runtime, "expiry-provider")
        _grant_service_reputation(runtime, provider_id)
        published = await runtime.dispatch(
            _context("expiry-publisher", "publish"), "发布服务 教学采集协助"
        )
        clock.advance(seconds=2)
        expired = await runtime.dispatch(
            _context("expiry-provider", "accept-expiry"),
            f"接取服务 {published.data['order_id']}",
        )
        assert expired.code == "SERVICE_EXPIRED"
        assert expired.data["idempotent_replay"] is False
        replay = await runtime.dispatch(
            _context("expiry-provider", "accept-expiry"),
            f"接取服务 {published.data['order_id']}",
        )
        assert replay.code == "SERVICE_EXPIRED"
        assert replay.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT spirit_stones FROM players WHERE platform_user_id='expiry-publisher'"
            ).fetchone()[0] == 100
            assert connection.execute(
                "SELECT status FROM livelihood_service_orders WHERE order_id=?", (published.data["order_id"],)
            ).fetchone()[0] == "expired"
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='accept-expiry'"
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_service_commands_reach_shared_application_through_real_adapters(tmp_path: Path, kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    async def run() -> None:
        data_dir = _content(tmp_path)
        runtime = create_runtime(
            data_dir=data_dir,
            clock=lambda: datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

        async def send(text: str, message_id: int, *, user: str):
            if kind == "onebot":
                event = _onebot_event(text, message_id, user_id=int(user), group_id=2002)
                normalized = normalize_event(event)
                adapter = "onebot.v11"
            else:
                event = _qq_event(text, str(message_id), member_openid=user, group_openid="qq-group-1")
                normalized = normalize_qq_event(event)
                adapter = "qq.official"
            return await runtime.adapters.dispatch(adapter, normalized.context, normalized.text)

        # The adapter flow itself is intentionally read/write through the same application;
        # reputation is only a role precondition for the service provider.
        await send("开始修仙", 8100, user="1001" if kind == "onebot" else "adapter-publisher")
        await send("寻仙问道", 8101, user="1001" if kind == "onebot" else "adapter-publisher")
        await send("开始修仙", 8102, user="1002" if kind == "onebot" else "adapter-provider")
        await send("寻仙问道", 8103, user="1002" if kind == "onebot" else "adapter-provider")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform_user_id=?",
                ("1002" if kind == "onebot" else "adapter-provider",),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                "VALUES (?, '{}', 10, ?)",
                (player_id, datetime.now(timezone.utc).isoformat()),
            )
        publisher = await send(
            "发布服务 教学采集协助", 8104, user="1001" if kind == "onebot" else "adapter-publisher"
        )
        assert publisher.code == "SERVICE_PUBLISHED"
        accepted = await send(
            f"接取服务 {publisher.data['order_id']}",
            8105,
            user="1002" if kind == "onebot" else "adapter-provider",
        )
        assert accepted.code == "SERVICE_ACCEPTED"
        await runtime.close()

    asyncio.run(run())
