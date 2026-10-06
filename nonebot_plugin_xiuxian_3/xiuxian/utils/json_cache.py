"""Strict JSON decoding and a read-only cache invalidated by file changes."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class DuplicateJSONKeyError(ValueError):
    """Raised when a JSON object repeats a member name."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def decode_json_strict(value: str) -> Any:
    """Decode persisted JSON with the same duplicate-key checks as content files."""
    return json.loads(value, object_pairs_hook=_unique_object)


@lru_cache(maxsize=256)
def _load_json(
    path: str,
    device: int,
    inode: int,
    modified_ns: int,
    changed_ns: int,
    size: int,
) -> Any:
    del device, inode, modified_ns, changed_ns, size
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_object)


def read_json_cached(path: str | Path) -> Any:
    file_path = Path(path).expanduser().resolve(strict=True)
    stat = file_path.stat()
    return copy.deepcopy(
        _load_json(
            str(file_path),
            stat.st_dev,
            stat.st_ino,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_size,
        )
    )


def clear_json_cache() -> None:
    _load_json.cache_clear()


__all__ = ["DuplicateJSONKeyError", "clear_json_cache", "decode_json_strict", "read_json_cached"]
