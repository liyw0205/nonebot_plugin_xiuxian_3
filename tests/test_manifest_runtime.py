from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiuxian3.bootstrap.config import RuntimeConfig
from xiuxian3.bootstrap.lifecycle import RuntimePhase
from xiuxian3.bootstrap.manifest import FeatureManifest, FeatureRegistry, ManifestError
from xiuxian3.infrastructure.paths import RuntimePaths
from xiuxian3.plugin import create_runtime


class ManifestTests(unittest.TestCase):
    def test_command_and_task_collisions_are_rejected(self) -> None:
        registry = FeatureRegistry()
        registry.register(FeatureManifest("one", "One", commands=("修炼",), task_ids=("daily",)))
        with self.assertRaises(ManifestError):
            registry.register(FeatureManifest("two", "Two", aliases=(" 修炼 ",)))
        with self.assertRaises(ManifestError):
            registry.register(FeatureManifest("three", "Three", task_ids=("daily",)))

        with self.assertRaises(ManifestError):
            FeatureManifest("four", "Four", commands=("same", " SAME "))
        with self.assertRaises(ManifestError):
            FeatureManifest("five", "Five", task_ids=("same-task", "same-task"))

    def test_required_ports_are_checked_before_activation(self) -> None:
        registry = FeatureRegistry(available_ports={"clock"})
        with self.assertRaises(ManifestError):
            registry.register(FeatureManifest("needs-random", "Needs random", required_ports=("random",)))

    def test_hooks_activate_once_and_deactivate_in_reverse(self) -> None:
        events: list[str] = []
        registry = FeatureRegistry()
        registry.register(
            FeatureManifest(
                "one",
                "One",
                on_start=lambda context: events.append(f"start:{context.feature_id}"),
                on_stop=lambda context: events.append(f"stop:{context.feature_id}"),
            )
        )
        registry.register(
            FeatureManifest(
                "two",
                "Two",
                on_start=lambda context: events.append(f"start:{context.feature_id}"),
                on_stop=lambda context: events.append(f"stop:{context.feature_id}"),
            )
        )
        self.assertEqual(registry.activate(), ("one", "two"))
        self.assertEqual(registry.activate(), ("one", "two"))
        registry.deactivate()
        self.assertEqual(events, ["start:one", "start:two", "stop:two", "stop:one"])

    def test_runtime_start_is_idempotent_and_health_is_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig.from_env({"XIUXIAN3_DATA_DIR": directory})
            runtime = create_runtime({"XIUXIAN3_DATA_DIR": directory})
            self.assertEqual(runtime.phase, RuntimePhase.CREATED)
            runtime.start()
            runtime.start()
            self.assertEqual(runtime.phase, RuntimePhase.READY)
            self.assertTrue(runtime.health().ready)
            self.assertEqual(runtime.registry.activated, ("runtime.core",))
            self.assertTrue((Path(directory) / "cache").is_dir())
            self.assertTrue((Path(directory) / "game.sqlite3").is_file())
            with runtime.database.connect() as connection:
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'operation_ledger'"
                    ).fetchone()
                )
            runtime.stop()
            self.assertEqual(runtime.phase, RuntimePhase.STOPPED)
            self.assertEqual(config.data_dir, Path(directory).resolve())
