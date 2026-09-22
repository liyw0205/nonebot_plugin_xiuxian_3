from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext, validate_command_identity
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.repository import PlayerNotFoundError, PlayerSuspendedError


def test_player_creation_and_seeking_are_idempotent_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("nonebot", "web"))
            contexts = [
                CommandContext(adapter="nonebot", user_id="same-user", nickname="道友")
                for _ in range(64)
            ]
            create_results = await asyncio.gather(
                *(runtime.dispatch(context, "开始修仙") for context in contexts)
            )
            assert all(result.ok for result in create_results)
            assert len({result.data["player_id"] for result in create_results}) == 1
            assert {result.data["stage"] for result in create_results} == {"new_user"}
            assert {result.data["dao_name"] for result in create_results} == {""}
            assert {result.data["spirit_stones"] for result in create_results} == {0}

            seek_results = await asyncio.gather(
                *(runtime.dispatch(context, "寻仙问道") for context in contexts)
            )
            assert all(result.ok for result in seek_results)
            assert len({result.data["player_id"] for result in seek_results}) == 1
            assert {result.data["spirit_stones"] for result in seek_results} == {100}
            assert {result.data["stage"] for result in seek_results} == {"mortal"}
            await runtime.close()

    asyncio.run(run())


def test_dao_name_creation_rename_and_qualification_labels() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            named = await runtime.dispatch(
                CommandContext(adapter="web", user_id="named-user"),
                "开始修仙 青云",
            )
            assert named.code == "PLAYER_CREATED"
            assert named.data["dao_name"] == "青云"
            assert "用户 ID" not in named.message

            duplicate = await runtime.dispatch(
                CommandContext(adapter="web", user_id="other-user"),
                "开始修仙 青云",
            )
            assert duplicate.code == "DAO_NAME_TAKEN"

            seeked = await runtime.dispatch(
                CommandContext(adapter="web", user_id="named-user"),
                "寻仙问道",
            )
            assert seeked.code == "SEEKING_STARTED"
            assert "体魄" in seeked.message
            assert "body" not in seeked.message
            assert "凡人" in seeked.message
            assert "mortal" not in seeked.message

            markdown_name = await runtime.dispatch(
                CommandContext(adapter="web", user_id="markdown-name"),
                "开始修仙 星*尘",
            )
            assert markdown_name.code == "PLAYER_CREATED"
            assert "星\\*尘" in markdown_name.message

            unnamed = await runtime.dispatch(
                CommandContext(adapter="web", user_id="unnamed-user"),
                "开始修仙",
            )
            assert unnamed.data["dao_name"] == ""
            renamed = await runtime.dispatch(
                CommandContext(adapter="web", user_id="unnamed-user"),
                "修仙改名 白云",
            )
            assert renamed.code == "DAO_NAME_CHANGED"
            assert renamed.data["dao_name"] == "白云"

            card_required = await runtime.dispatch(
                CommandContext(adapter="web", user_id="unnamed-user"),
                "修仙改名 流云",
            )
            assert card_required.code == "RENAME_CARD_REQUIRED"

            too_long = await runtime.dispatch(
                CommandContext(adapter="web", user_id="long-name-user"),
                "开始修仙 一二三四五六七八",
            )
            assert too_long.code == "INVALID_DAO_NAME"
            await runtime.close()

    asyncio.run(run())


def test_multiple_adapters_share_one_application() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("nonebot", "web"))
            missing = await runtime.adapters.dispatch(
                "nonebot",
                CommandContext(adapter="nonebot", user_id="n-1"),
                "寻仙问道",
            )
            assert missing.code == "PLAYER_NOT_FOUND"
            await runtime.adapters.dispatch(
                "nonebot",
                CommandContext(adapter="nonebot", user_id="n-1"),
                "开始修仙",
            )
            nonebot_result = await runtime.adapters.dispatch(
                "nonebot",
                CommandContext(adapter="nonebot", user_id="n-1"),
                "寻仙问道",
            )
            await runtime.adapters.dispatch(
                "web",
                CommandContext(adapter="web", user_id="w-1"),
                "开始修仙",
            )
            web_result = await runtime.adapters.dispatch(
                "web", CommandContext(adapter="web", user_id="w-1"), "寻仙问道"
            )
            rejected = await runtime.adapters.dispatch(
                "unknown",
                CommandContext(adapter="unknown", user_id="x-1"),
                "寻仙问道",
            )
            assert nonebot_result.code == "SEEKING_STARTED"
            assert web_result.code == "SEEKING_STARTED"
            assert rejected.code == "ADAPTER_NOT_REGISTERED"
            await runtime.close()

    asyncio.run(run())


def test_burst_of_distinct_users_is_safe() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        CommandContext(adapter="web", user_id=f"user-{index}"),
                        "开始修仙",
                    )
                    for index in range(120)
                )
            )
            assert all(result.code in {"PLAYER_CREATED", "PLAYER_ALREADY_EXISTS"} for result in results)
            assert len({result.data["player_id"] for result in results}) == 120
            await runtime.close()

    asyncio.run(run())


def test_invalid_context_returns_stable_error() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            result = await runtime.dispatch(
                CommandContext(adapter="web", user_id=""),
                "开始修仙",
            )
            assert result.ok is False
            assert result.code == "INVALID_CONTEXT"
            await runtime.close()

    asyncio.run(run())


def test_shared_identity_validation_separates_read_and_write_checks() -> None:
    invalid = validate_command_identity(CommandContext(adapter="web", user_id=""))
    assert invalid is not None
    assert invalid.code == "INVALID_CONTEXT"

    read_only = validate_command_identity(
        CommandContext(adapter="web", user_id="reader", can_write_assets=False)
    )
    assert read_only is None

    write_blocked = validate_command_identity(
        CommandContext(adapter="web", user_id="writer", can_write_assets=False),
        require_write=True,
        write_message="禁止写入。",
    )
    assert write_blocked is not None
    assert write_blocked.message == "禁止写入。"

    malformed = validate_command_identity(CommandContext(adapter=None, user_id=123))
    assert malformed is not None
    assert malformed.code == "INVALID_CONTEXT"


def test_repository_identity_lookup_is_shared_and_transaction_local() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            with runtime.repository._connect() as connection:
                try:
                    runtime.repository._require_player(connection, "web", "missing")
                except PlayerNotFoundError:
                    pass
                else:
                    raise AssertionError("missing identity bypassed the shared repository check")

            created = await runtime.dispatch(
                CommandContext(adapter="web", user_id="suspended-user"),
                "开始修仙",
            )
            assert created.ok
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET status = 'suspended' WHERE platform = ? AND platform_user_id = ?",
                    ("web", "suspended-user"),
                )
                for writable in (True, False):
                    try:
                        runtime.repository._require_player(
                            connection,
                            "web",
                            "suspended-user",
                            writable=writable,
                        )
                    except PlayerSuspendedError:
                        pass
                    else:
                        raise AssertionError("suspended identity bypassed the shared repository check")
            await runtime.close()

    asyncio.run(run())


def test_every_registered_command_uses_shared_identity_validation() -> None:
    """All feature modules must reject an unidentified event at the boundary."""

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(adapter="web", user_id="")

            for command in runtime.router.commands:
                result = await runtime.dispatch(context, command)
                assert result.code == "INVALID_CONTEXT", (
                    f"{command!r} bypassed shared identity validation: "
                    f"{result.code}"
                )

            await runtime.close()

    asyncio.run(run())


def test_read_only_commands_accept_read_only_identity() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(
                adapter="web",
                user_id="read-only-user",
                can_write_assets=False,
            )
            read_only_commands = (
                "我的状态",
                "我的修仙信息",
                "悬赏榜",
                "生产预览",
                "移动预览",
                "突破预览",
                "我的道契",
            )

            for command in read_only_commands:
                result = await runtime.dispatch(context, command)
                assert result.code != "INVALID_CONTEXT", (
                    f"read-only command {command!r} unexpectedly requires write access"
                )

            await runtime.close()

    asyncio.run(run())


def test_operation_replay_conflict_and_read_only_profile() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            create_context = CommandContext(
                adapter="web",
                user_id="replay-user",
                nickname="道友",
                operation_id="op-create-1",
            )
            first = await runtime.dispatch(create_context, "开始修仙")
            replay = await runtime.dispatch(create_context, "开始修仙")
            assert first.code == "PLAYER_CREATED"
            assert first.message.startswith("## 身份登记完成")
            assert replay.code == "PLAYER_CREATED"
            assert replay.data["idempotent_replay"] is True

            conflict = await runtime.dispatch(
                CommandContext(
                    adapter="web",
                    user_id="replay-user",
                    nickname="换名",
                    operation_id="op-create-1",
                ),
                "开始修仙",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            profile = await runtime.dispatch(
                CommandContext(adapter="web", user_id="replay-user"), "我的状态"
            )
            assert profile.code == "PROFILE_READ"
            assert profile.message.startswith("## 我的修仙信息")
            assert "新用户" in profile.message
            assert "active" not in profile.message
            assert "xuantian.new_town" not in profile.message
            assert profile.data["stage"] == "new_user"
            assert profile.data["spirit_stones"] == 0
            await runtime.close()

    asyncio.run(run())
