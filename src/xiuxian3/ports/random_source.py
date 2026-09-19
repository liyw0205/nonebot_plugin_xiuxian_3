"""Randomness port for rule-versioned outcomes."""

from typing import Protocol


class RandomSource(Protocol):
    def randbelow(self, upper_bound: int) -> int:
        """Return a value in [0, upper_bound)."""