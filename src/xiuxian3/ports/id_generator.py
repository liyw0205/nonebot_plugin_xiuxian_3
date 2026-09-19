"""Identifier port for operation and request IDs."""

from typing import Protocol


class IdGenerator(Protocol):
    def new_id(self) -> str:
        """Return a new opaque identifier."""