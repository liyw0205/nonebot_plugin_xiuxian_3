"""Read-only loader for the runtime content configuration."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .utils.json_cache import DuplicateJSONKeyError, read_json_cached


class ContentError(ValueError):
    """Raised when the runtime content configuration is malformed."""


@dataclass(frozen=True, slots=True)
class ContentBundle:
    """Validated content records indexed by ``(kind, key)``."""

    root: Path
    manifest: Mapping[str, Any]
    _records: Mapping[tuple[str, str], Mapping[str, Any]]

    @classmethod
    def load(cls, data_dir: str | Path) -> "ContentBundle":
        root = Path(data_dir).expanduser().resolve()
        manifest_path = root / "内容清单.json"
        manifest = _read_object(manifest_path)
        if manifest.get("schema") != "xiuxian.content":
            raise ContentError(f"invalid content schema: {manifest_path}")
        files = manifest.get("files")
        if not isinstance(files, list) or not files or any(not isinstance(item, str) for item in files):
            raise ContentError(f"manifest files must be a non-empty string list: {manifest_path}")
        if len(set(files)) != len(files):
            raise ContentError(f"manifest contains duplicate file entries: {manifest_path}")

        records: dict[tuple[str, str], Mapping[str, Any]] = {}
        for relative_path in files:
            file_path = _safe_child(root, relative_path)
            document = _read_object(file_path)
            if document.get("schema") != "xiuxian.content":
                raise ContentError(f"invalid content schema: {file_path}")
            kind = document.get("kind")
            if not isinstance(kind, str) or not kind:
                raise ContentError(f"missing content kind: {file_path}")
            rows = document.get("records")
            if not isinstance(rows, list):
                raise ContentError(f"records must be a list: {file_path}")
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"]:
                    raise ContentError(f"record {index} has no string key: {file_path}")
                identity = (kind, row["key"])
                if identity in records:
                    raise ContentError(f"duplicate content key {kind}:{row['key']}")
                records[identity] = copy.deepcopy(row)

        return cls(
            root=root,
            manifest=copy.deepcopy(manifest),
            _records=records,
        )

    @classmethod
    def load_optional(cls, data_dir: str | Path) -> "ContentBundle | None":
        manifest_path = Path(data_dir).expanduser() / "内容清单.json"
        if not manifest_path.is_file():
            return None
        return cls.load(data_dir)

    def get(self, kind: str, key: str, *, include_locked: bool = True) -> dict[str, Any] | None:
        row = self._records.get((kind, key))
        if row is None:
            return None
        if not include_locked and row.get("status") not in {"active", "open"}:
            return None
        return copy.deepcopy(dict(row))

    def require(self, kind: str, key: str, *, include_locked: bool = True) -> dict[str, Any]:
        row = self.get(kind, key, include_locked=include_locked)
        if row is None:
            raise KeyError(f"content record not found: {kind}:{key}")
        return row

    def list(self, kind: str, *, include_locked: bool = True) -> list[dict[str, Any]]:
        rows = [row for (row_kind, _), row in self._records.items() if row_kind == kind]
        if not include_locked:
            rows = [row for row in rows if row.get("status") in {"active", "open"}]
        return copy.deepcopy([dict(row) for row in rows])

    def has(self, kind: str, key: str, *, include_locked: bool = True) -> bool:
        return self.get(kind, key, include_locked=include_locked) is not None

    def label(self, kind: str, key: str, *, fallback: str | None = None) -> str:
        """Return the user-facing name for a stable content key.

        Presentation code should use this instead of keeping another key to
        label mapping.  ``fallback`` is intentionally explicit so isolated
        tests and old databases can keep their compatibility text.
        """

        row = self.get(kind, key)
        if row is None or not isinstance(row.get("name"), str) or not row["name"].strip():
            if fallback is not None:
                return fallback
            raise KeyError(f"content label not found: {kind}:{key}")
        return row["name"].strip()

def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = read_json_cached(path)
    except FileNotFoundError as exc:
        raise ContentError(f"content file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContentError(f"invalid JSON: {path}: {exc.msg}") from exc
    except DuplicateJSONKeyError as exc:
        raise ContentError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContentError(f"content document must be an object: {path}")
    return value


def _safe_child(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise ContentError(f"content path escapes data directory: {relative_path}")
    if candidate.suffix != ".json":
        raise ContentError(f"content file must be JSON: {relative_path}")
    return candidate


def bundled_content(data_dir: str | Path | None = None) -> ContentBundle:
    """Load the packaged content, or the source-tree data while developing."""

    if data_dir is not None:
        return ContentBundle.load(data_dir)

    package_data = Path(__file__).resolve().parents[1] / "data"
    source_data = Path(__file__).resolve().parents[2] / "data"
    for root in (package_data, source_data):
        if (root / "内容清单.json").is_file():
            return ContentBundle.load(root)
    raise FileNotFoundError(
        f"content manifest not found in {package_data} or {source_data}"
    )


__all__ = ["ContentBundle", "ContentError", "bundled_content"]
