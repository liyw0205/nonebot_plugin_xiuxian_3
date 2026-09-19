from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from xiuxian3.bootstrap.config import ConfigError, RuntimeConfig
from xiuxian3.infrastructure.paths import PathBoundaryError, RuntimePaths


class ConfigAndPathTests(unittest.TestCase):
    def test_web_secret_is_persisted_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimeConfig.from_env(
                {"XIUXIAN3_DATA_DIR": directory, "XIUXIAN3_WEB_ENABLED": "true"}
            )
            secret_path = Path(directory) / ".web_secret_key"
            self.assertTrue(secret_path.is_file())
            self.assertEqual(config.web_secret_key, secret_path.read_text(encoding="utf-8"))
            self.assertNotIn(config.web_secret_key, str(config.redacted()))
            self.assertEqual(config.redacted()["web_secret_key_configured"], True)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            RuntimeConfig.from_env({"XIUXIAN3_WEB_ENABLED": "sometimes"})

    def test_runtime_paths_reject_traversal_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = RuntimePaths.from_root(Path(directory))
            self.assertEqual(paths.resolve("cache/item"), Path(directory) / "cache/item")
            for value in ("../outside", "/tmp/outside", "a/../outside"):
                with self.subTest(value=value):
                    with self.assertRaises(PathBoundaryError):
                        paths.resolve(value)

    def test_runtime_paths_reject_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            paths = RuntimePaths.from_root(Path(directory))
            link = Path(directory) / "cache"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(PathBoundaryError):
                paths.resolve("cache/file")

    def test_environment_is_not_mutated(self) -> None:
        original = dict(os.environ)
        RuntimeConfig.from_env({"XIUXIAN3_DATA_DIR": "data"})
        self.assertEqual(dict(os.environ), original)