from __future__ import annotations

import unittest

from xiuxian3.adapters.contracts import (
    CommandContext,
    MessageCapability,
    ReplyPlan,
    ReplyRenderer,
    Scene,
)
from xiuxian3.adapters.normalization import normalize_event


class AdapterContractTests(unittest.TestCase):
    def test_onebot_group_event_becomes_writable_group_context(self) -> None:
        context = normalize_event(
            "onebot.v11",
            {
                "user_id": 1001,
                "group_id": 2002,
                "message_id": 3003,
                "raw_message": "修炼",
                "reply_to": 99,
            },
        )
        self.assertEqual(context.scene, Scene.GROUP)
        self.assertEqual(context.actor_id, "1001")
        self.assertEqual(context.group_id, "2002")
        self.assertTrue(context.can_write_assets)
        self.assertEqual(context.message_id, "3003")

    def test_qq_c2c_event_becomes_private_context(self) -> None:
        context = normalize_event(
            "qq",
            {"author_id": "u-1", "id": "m-1", "content": "我的状态", "direct": True},
        )
        self.assertEqual(context.scene, Scene.PRIVATE)
        self.assertEqual(context.actor_id, "u-1")
        self.assertIsNone(context.group_id)
        self.assertTrue(context.can_write_assets)

    def test_channel_public_and_private_scenes_are_distinct(self) -> None:
        public = normalize_event(
            "qq",
            {"author_id": "u-1", "id": "m-1", "content": "地图", "channel_id": "c-1"},
        )
        private = normalize_event(
            "qq",
            {
                "author_id": "u-1",
                "id": "m-2",
                "content": "地图",
                "channel_id": "c-1",
                "direct": True,
            },
        )
        self.assertEqual(public.scene, Scene.CHANNEL_GROUP)
        self.assertEqual(private.scene, Scene.CHANNEL_PRIVATE)
        self.assertTrue(public.can_write_assets)
        self.assertTrue(private.can_write_assets)

    def test_unknown_or_incomplete_event_cannot_write_assets(self) -> None:
        unknown = normalize_event("unknown", {"user_id": "u-1", "message_id": "m-1"})
        missing_actor = normalize_event("qq", {"id": "m-1", "content": "修炼"})
        self.assertEqual(unknown.scene, Scene.UNKNOWN)
        self.assertFalse(unknown.can_write_assets)
        self.assertFalse(missing_actor.can_write_assets)

    def test_reply_renderer_degrades_without_changing_plan_semantics(self) -> None:
        plan = ReplyPlan(
            text="状态正常",
            markdown="# 状态正常",
            keyboard=("修炼", "背包"),
            image_url="https://example.invalid/status.png",
            reference_message_id="m-1",
        )
        capable = ReplyRenderer({MessageCapability.MARKDOWN, MessageCapability.KEYBOARD})
        limited = ReplyRenderer({MessageCapability.TEXT})
        rich = capable.render(plan)
        plain = limited.render(plan)
        self.assertEqual(rich.markdown, "# 状态正常")
        self.assertEqual(rich.keyboard, ("修炼", "背包"))
        self.assertIsNone(rich.image_url)
        self.assertEqual(plain.text, "状态正常")
        self.assertIsNone(plain.markdown)
        self.assertIsNone(plain.keyboard)
        self.assertIsNone(plain.image_url)
        self.assertEqual(plain.reference_message_id, "m-1")

    def test_context_is_serializable_dto_without_platform_objects(self) -> None:
        context = CommandContext(
            actor_id="u-1",
            scene=Scene.PRIVATE,
            group_id=None,
            message_id="m-1",
            text="状态",
            raw_text_digest="digest",
            reply_to_message_id=None,
            capabilities=frozenset({MessageCapability.TEXT}),
            can_write_assets=True,
        )
        self.assertEqual(context.text, "状态")
        self.assertEqual(context.capabilities, frozenset({MessageCapability.TEXT}))