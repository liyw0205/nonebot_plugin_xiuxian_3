from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import RewardContentError, reward_definition


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def test_onboarding_reward_is_loaded_from_content_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            reward_file = data_dir / "奖励" / "奖励.json"
            document = json.loads(reward_file.read_text(encoding="utf-8"))
            record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
            next(entry for entry in record["entries"] if entry["kind"] == "currency")["quantity"] = 777
            stamina = next(entry for entry in record["entries"] if entry.get("resource_key") == "stamina")
            stamina["quantity"] = 42
            stamina["set_max"] = 42
            reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            try:
                for adapter in ("qq.official", "onebot.v11"):
                    user = f"reward-{adapter}"
                    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
                    started = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道"
                    )
                    assert started.code == "SEEKING_STARTED"
                    assert started.data["spirit_stones"] == 777
                    assert started.data["stamina"] == 42
                    assert started.data["stamina_max"] == 42
                    assert started.data["reward"] == {
                        "spirit_stones": 777,
                        "item.food.coarse_spirit_rice": 3,
                        "item.herb.blood_grass": 3,
                        "stamina": 42,
                        "energy": 30,
                    }
                    replay = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道"
                    )
                    assert replay.code == "SEEKING_ALREADY_DONE"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == started.data["reward"]
                    conflict = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-seek"),
                        "寻仙问道 木",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"
            finally:
                await runtime.close()
            recovered = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            try:
                replay = await recovered.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", "reward-qq.official", "qq.official-seek"),
                    "寻仙问道",
                )
                assert replay.code == "SEEKING_ALREADY_DONE"
                assert replay.data["idempotent_replay"] is True
            finally:
                await recovered.close()

    asyncio.run(run())


def test_reward_parser_rejects_unknown_item_and_wrong_operation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
    record["entries"].append({"kind": "item", "item_key": "item.不存在", "quantity": 1})
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "inactive item" in str(exc)
    else:
        raise AssertionError("unknown reward item must fail content validation")

    clean_bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    try:
        reward_definition("reward.onboarding.seeking", clean_bundle, operation="other.operation")
    except RewardContentError as exc:
        assert "belongs to player.start_seeking" in str(exc)
    else:
        raise AssertionError("a reward must not be applied to a different operation")


def test_reward_parser_rejects_invalid_quantity_and_maximum(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")

    next(entry for entry in record["entries"] if entry["kind"] == "currency")["quantity"] = 0
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "quantity must be positive" in str(exc)
    else:
        raise AssertionError("zero reward quantity must fail content validation")

    document = json.loads((Path(__file__).parents[1] / "data" / "奖励" / "奖励.json").read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
    next(entry for entry in record["entries"] if entry.get("resource_key") == "stamina")["set_max"] = "yes"
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "set_max must be positive" in str(exc)
    else:
        raise AssertionError("invalid set_max must fail content validation")
