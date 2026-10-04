"""Deterministic random selection helpers shared by game domains."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import TypeVar


T = TypeVar("T")


def deterministic_weighted_choice(outcomes: Iterable[tuple[int, T]], seed: str) -> T:
    """Choose from positive integer weights using a stable seed."""

    if not isinstance(seed, str):
        raise ValueError("weighted choice seed must be a string")
    entries = tuple(outcomes)
    if not entries:
        raise ValueError("weighted choice requires at least one outcome")

    total_weight = 0
    for outcome in entries:
        if not isinstance(outcome, tuple) or len(outcome) != 2:
            raise ValueError("weighted choice outcomes must be (weight, value) pairs")
        weight = outcome[0]
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise ValueError("weighted choice weights must be positive integers")
        total_weight += weight

    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    cursor = int.from_bytes(digest, "big") % total_weight
    for weight, value in entries:
        if cursor < weight:
            return value
        cursor -= weight
    raise AssertionError("weighted choice fell through")


__all__ = ["deterministic_weighted_choice"]
