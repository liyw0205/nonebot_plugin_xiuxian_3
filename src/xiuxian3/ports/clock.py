"""Business-time port; domain code receives a Clock instead of reading time."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current business instant."""