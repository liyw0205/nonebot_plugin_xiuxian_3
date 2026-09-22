"""Persistence implementations and storage infrastructure."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for static type checkers
    from .sqlite_repository import SQLitePlayerRepository

__all__ = ["SQLitePlayerRepository"]


def __getattr__(name: str):
    """Load the concrete repository only when its compatibility API is used."""

    if name == "SQLitePlayerRepository":
        from .sqlite_repository import SQLitePlayerRepository

        return SQLitePlayerRepository
    raise AttributeError(name)
