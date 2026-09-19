"""Runtime lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import RuntimeConfig
from .health import HealthReport, local_health
from .manifest import FeatureManifest, FeatureRegistry
from ..infrastructure.paths import RuntimePaths
from ..infrastructure.sqlite import SQLiteDatabase
from ..ports.clock import Clock
from ..ports.id_generator import IdGenerator
from ..ports.random_source import RandomSource


class LifecycleError(RuntimeError):
    """Raised when lifecycle transitions are invalid."""


class RuntimePhase(str, Enum):
    CREATED = "created"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    clock: Clock
    random: RandomSource
    ids: IdGenerator


class Runtime:
    """Composition-root owned runtime with explicit, repeat-safe lifecycle."""

    def __init__(
        self,
        config: RuntimeConfig,
        paths: RuntimePaths,
        dependencies: RuntimeDependencies,
        registry: FeatureRegistry,
        manifests: tuple[FeatureManifest, ...],
        database: SQLiteDatabase,
    ) -> None:
        self.config = config
        self.paths = paths
        self.dependencies = dependencies
        self.registry = registry
        self.manifests = manifests
        self.database = database
        self.phase = RuntimePhase.CREATED

    def start(self) -> "Runtime":
        if self.phase is RuntimePhase.READY:
            return self
        if self.phase is not RuntimePhase.CREATED:
            raise LifecycleError(f"cannot start runtime from {self.phase.value}")
        try:
            self.paths.ensure_layout()
            self.database.migrate()
            self.registry.register_many(self.manifests)
            self.registry.activate()
            self.phase = RuntimePhase.READY
        except Exception:
            self.phase = RuntimePhase.FAILED
            raise
        return self

    def stop(self) -> None:
        if self.phase is RuntimePhase.STOPPED:
            return
        if self.phase is not RuntimePhase.READY:
            raise LifecycleError(f"cannot stop runtime from {self.phase.value}")
        self.phase = RuntimePhase.STOPPING
        self.registry.deactivate()
        self.phase = RuntimePhase.STOPPED

    def health(self) -> HealthReport:
        return local_health(
            started=self.phase is RuntimePhase.READY,
            data_dir=self.paths.root,
            activated_features=self.registry.activated,
        )