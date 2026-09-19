"""Composition root for P1; platform adapters are not imported here."""

from __future__ import annotations

from .config import RuntimeConfig
from .lifecycle import Runtime, RuntimeDependencies
from .manifest import FeatureManifest, FeatureRegistry
from ..features.core import core_manifest
from ..infrastructure.clock import SystemClock
from ..infrastructure.ids import UuidIdGenerator
from ..infrastructure.paths import RuntimePaths
from ..infrastructure.random import SystemRandomSource
from ..infrastructure.sqlite import SQLiteDatabase


def build_runtime(config: RuntimeConfig) -> Runtime:
    paths = RuntimePaths.from_root(config.data_dir)
    database = SQLiteDatabase(paths.resolve("game.sqlite3"))
    dependencies = RuntimeDependencies(
        clock=SystemClock(),
        random=SystemRandomSource(),
        ids=UuidIdGenerator(),
    )
    manifests: tuple[FeatureManifest, ...] = (core_manifest(),)
    registry = FeatureRegistry(
        enabled_flags={"web": config.web_enabled},
        available_ports={"clock", "random", "ids"},
    )
    return Runtime(config, paths, dependencies, registry, manifests, database)