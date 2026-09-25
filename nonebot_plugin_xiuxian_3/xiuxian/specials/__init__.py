"""Independent special-gameplay domains."""

from .arena_models import (
    ArenaClaimRecord,
    ArenaMatchRecord,
    ArenaReplayRecord,
    ArenaSnapshotRecord,
)
from .arena_repository import ArenaRepositoryMixin
from .team_arena_models import TeamArenaMatchRecord, TeamArenaReplayRecord, TeamArenaSnapshotRecord
from .team_arena_repository import TeamArenaRepositoryMixin
from .three_realms_arena_rules import THREE_REALMS_ARENA_MODE_KEY
from .arena_recovery_repository import (
    ArenaRecoveryArtifact,
    ArenaRecoveryReport,
    ArenaRecoveryRepositoryMixin,
)

__all__ = [
    "ArenaClaimRecord",
    "ArenaMatchRecord",
    "ArenaReplayRecord",
    "ArenaRepositoryMixin",
    "ArenaSnapshotRecord",
    "TeamArenaMatchRecord",
    "TeamArenaReplayRecord",
    "TeamArenaRepositoryMixin",
    "TeamArenaSnapshotRecord",
    "THREE_REALMS_ARENA_MODE_KEY",
    "ArenaRecoveryArtifact",
    "ArenaRecoveryReport",
    "ArenaRecoveryRepositoryMixin",
]
