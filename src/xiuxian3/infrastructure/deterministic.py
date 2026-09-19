"""Deterministic port implementations used by isolated tests and fixtures."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class SequenceRandom:
    def __init__(self, values: Iterable[int]) -> None:
        self._values = iter(values)

    def randbelow(self, upper_bound: int) -> int:
        value = next(self._values)
        if not 0 <= value < upper_bound:
            raise ValueError("deterministic random value is outside the requested bound")
        return value


class SequenceIdGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)