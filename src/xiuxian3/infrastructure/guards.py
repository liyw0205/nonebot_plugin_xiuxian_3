"""Request deduplication and process-local rate-limit implementations."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

from ..ports.clock import Clock


class InMemoryRequestDeduplicator:
    """TTL-based event deduplication; replacement with a shared port is explicit."""

    def __init__(self, clock: Clock, *, ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError("deduplication ttl must be positive")
        self._clock = clock
        self._ttl = ttl
        self._seen: dict[str, datetime] = {}

    def first_seen(self, event_key: str) -> bool:
        if not event_key:
            raise ValueError("event key cannot be empty")
        now = self._clock.now()
        expires_at = self._seen.get(event_key)
        if expires_at is not None and now < expires_at:
            return False
        self._seen[event_key] = now + self._ttl
        self._discard_expired(now)
        return True

    def _discard_expired(self, now: datetime) -> None:
        expired = [key for key, expires_at in self._seen.items() if now >= expires_at]
        for key in expired:
            self._seen.pop(key, None)


@dataclass(frozen=True, slots=True)
class RateLimitKey:
    actor_id: str
    scene: str
    scope_id: str | None

    def __post_init__(self) -> None:
        if not self.actor_id or not self.scene:
            raise ValueError("actor_id and scene are required")


@dataclass(slots=True)
class _Bucket:
    started_at: datetime
    count: int = 0


BucketKey = TypeVar("BucketKey")


class InMemoryRateLimiter:
    """Fixed-window user, scene and global limiter with atomic admission."""

    def __init__(
        self,
        clock: Clock,
        *,
        user_limit: int,
        scene_limit: int,
        global_limit: int,
        window: timedelta = timedelta(minutes=1),
    ) -> None:
        if min(user_limit, scene_limit, global_limit) <= 0:
            raise ValueError("rate limits must be positive")
        if window <= timedelta(0):
            raise ValueError("rate-limit window must be positive")
        self._clock = clock
        self._user_limit = user_limit
        self._scene_limit = scene_limit
        self._global_limit = global_limit
        self._window = window
        self._users: dict[str, _Bucket] = {}
        self._scenes: dict[tuple[str, str | None], _Bucket] = {}
        self._global = _Bucket(clock.now())

    def allow(self, key: RateLimitKey) -> bool:
        now = self._clock.now()
        user = self._bucket(self._users, key.actor_id, now)
        scene = self._bucket(self._scenes, (key.scene, key.scope_id), now)
        global_bucket = self._global_bucket(now)
        if (
            user.count >= self._user_limit
            or scene.count >= self._scene_limit
            or global_bucket.count >= self._global_limit
        ):
            return False
        user.count += 1
        scene.count += 1
        global_bucket.count += 1
        return True

    def _bucket(
        self,
        buckets: MutableMapping[BucketKey, _Bucket],
        key: BucketKey,
        now: datetime,
    ) -> _Bucket:
        bucket = buckets.get(key)
        if bucket is None or now - bucket.started_at >= self._window:
            bucket = _Bucket(now)
            buckets[key] = bucket
        return bucket

    def _global_bucket(self, now: datetime) -> _Bucket:
        if now - self._global.started_at >= self._window:
            self._global = _Bucket(now)
        return self._global