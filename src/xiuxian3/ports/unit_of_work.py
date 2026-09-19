"""Application-owned transaction protocol."""

from typing import Protocol

from .operation_store import OperationStore
from .player_repository import PlayerRepository


class UnitOfWork(Protocol):
    operations: OperationStore
    players: PlayerRepository