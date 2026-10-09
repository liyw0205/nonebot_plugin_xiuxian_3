"""Shared pytest setup so every test starts from content only, never local runtime state."""

from __future__ import annotations

import shutil
from typing import Any

# Most tests copy the repository ``data/`` directory into a temporary path and open the
# runtime from that copy.  ``data/xiuxian3.sqlite3`` is a gitignored runtime artifact owned
# by whatever bot last ran on this machine, so a plain copy handed every sandbox the
# operator's live database: players, codex entries and operation rows from unrelated runs
# leaked in and assertions started to depend on local history.  Content copies must never
# carry runtime artifacts; an explicit ``ignore`` from the caller still wins.
RUNTIME_ARTIFACT_PATTERNS = (
    "*.sqlite3",
    "*.sqlite",
    "*.db",
    "*.log",
    "*.sqlite3-journal",
    "*.sqlite3-wal",
    "*.sqlite3-shm",
    "__pycache__",
    ".pytest_cache",
)

_original_copytree = shutil.copytree


def _copytree_without_runtime_artifacts(*args: Any, **kwargs: Any) -> Any:
    # ``shutil.copytree`` recurses through this module attribute with ``ignore`` already
    # filled in positionally, so nested directories must pass through untouched.
    if len(args) <= 3 and "ignore" not in kwargs:
        kwargs["ignore"] = shutil.ignore_patterns(*RUNTIME_ARTIFACT_PATTERNS)
    return _original_copytree(*args, **kwargs)


shutil.copytree = _copytree_without_runtime_artifacts
