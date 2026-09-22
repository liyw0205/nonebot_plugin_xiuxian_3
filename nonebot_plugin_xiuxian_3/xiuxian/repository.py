"""Compatibility facade for the SQLite repository.

Application services keep importing this stable path. The implementation is
under :mod:`xiuxian.persistence`, while domain-specific transactions are
provided by the progression and world repository mixins.
"""

from .persistence.sqlite_repository import *  # noqa: F401,F403
from .persistence.sqlite_repository import SQLitePlayerRepository

__all__ = [
    name
    for name in globals()
    if not name.startswith("_")
]
