from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from xiuxian3.infrastructure.deterministic import FixedClock
from xiuxian3.infrastructure.guards import (
    InMemoryRequestDeduplicator,
    InMemoryRateLimiter,
    RateLimitKey,
)


class RequestGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))

    def test_event_deduplicator_accepts_once_until_expiry(self) -> None:
        deduplicator = InMemoryRequestDeduplicator(self.clock, ttl=timedelta(seconds=10))
        self.assertTrue(deduplicator.first_seen("event-1"))
        self.assertFalse(deduplicator.first_seen("event-1"))
        self.clock.value += timedelta(seconds=11)
        self.assertTrue(deduplicator.first_seen("event-1"))

    def test_user_group_and_global_buckets_are_independent(self) -> None:
        limiter = InMemoryRateLimiter(
            self.clock,
            user_limit=2,
            scene_limit=2,
            global_limit=3,
            window=timedelta(seconds=60),
        )
        user = RateLimitKey(actor_id="u-1", scene="group", scope_id="g-1")
        other_user = RateLimitKey(actor_id="u-2", scene="group", scope_id="g-2")
        self.assertTrue(limiter.allow(user))
        self.assertTrue(limiter.allow(user))
        self.assertFalse(limiter.allow(user))
        self.assertTrue(limiter.allow(other_user))
        self.assertFalse(limiter.allow(other_user))
        # The third accepted request consumed the global budget.
        self.assertFalse(limiter.allow(RateLimitKey(actor_id="u-3", scene="private", scope_id=None)))

    def test_rejection_does_not_partially_consume_other_buckets(self) -> None:
        limiter = InMemoryRateLimiter(
            self.clock,
            user_limit=1,
            scene_limit=10,
            global_limit=10,
            window=timedelta(seconds=60),
        )
        key = RateLimitKey(actor_id="u-1", scene="private", scope_id=None)
        self.assertTrue(limiter.allow(key))
        self.assertFalse(limiter.allow(key))
        other_user = RateLimitKey(actor_id="u-2", scene="private", scope_id=None)
        self.assertTrue(limiter.allow(other_user))

    def test_scene_bucket_blocks_same_group_but_not_private(self) -> None:
        limiter = InMemoryRateLimiter(
            self.clock,
            user_limit=10,
            scene_limit=1,
            global_limit=10,
            window=timedelta(seconds=60),
        )
        group_a = RateLimitKey(actor_id="u-1", scene="group", scope_id="g-1")
        group_b = RateLimitKey(actor_id="u-2", scene="group", scope_id="g-1")
        private = RateLimitKey(actor_id="u-2", scene="private", scope_id=None)
        self.assertTrue(limiter.allow(group_a))
        self.assertFalse(limiter.allow(group_b))
        self.assertTrue(limiter.allow(private))

    def test_limits_reset_at_window_boundary(self) -> None:
        limiter = InMemoryRateLimiter(
            self.clock,
            user_limit=1,
            scene_limit=10,
            global_limit=10,
            window=timedelta(seconds=60),
        )
        key = RateLimitKey(actor_id="u-1", scene="private", scope_id=None)
        self.assertTrue(limiter.allow(key))
        self.assertFalse(limiter.allow(key))
        self.clock.value += timedelta(seconds=60)
        self.assertTrue(limiter.allow(key))

    def test_instances_do_not_share_test_state(self) -> None:
        key = RateLimitKey(actor_id="u-1", scene="private", scope_id=None)
        first = InMemoryRateLimiter(self.clock, user_limit=1, scene_limit=1, global_limit=1)
        second = InMemoryRateLimiter(self.clock, user_limit=1, scene_limit=1, global_limit=1)
        self.assertTrue(first.allow(key))
        self.assertTrue(second.allow(key))