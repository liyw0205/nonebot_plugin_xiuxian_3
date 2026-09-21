"""Read-only loader for the versioned runtime content configuration."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ContentError(ValueError):
    """Raised when the runtime content configuration is malformed."""


@dataclass(frozen=True, slots=True)
class ContentBundle:
    """Validated content records indexed by ``(kind, key)``."""

    root: Path
    manifest: Mapping[str, Any]
    _records: Mapping[tuple[str, str], Mapping[str, Any]]

    @property
    def content_version(self) -> str:
        return str(self.manifest["content_version"])

    @property
    def rule_version(self) -> str:
        return str(self.manifest["rule_version"])

    @classmethod
    def load(cls, data_dir: str | Path) -> "ContentBundle":
        root = Path(data_dir).expanduser()
        manifest_path = root / "内容清单.json"
        manifest = _read_object(manifest_path)
        if manifest.get("schema") != "xiuxian.content":
            raise ContentError(f"invalid content schema: {manifest_path}")
        if manifest.get("schema_version") != 1:
            raise ContentError(f"unsupported content schema version: {manifest_path}")
        if not isinstance(manifest.get("content_version"), str) or not isinstance(
            manifest.get("rule_version"), str
        ):
            raise ContentError(f"content and rule versions are required: {manifest_path}")

        files = manifest.get("files")
        if not isinstance(files, list) or not files or any(not isinstance(item, str) for item in files):
            raise ContentError(f"manifest files must be a non-empty string list: {manifest_path}")

        records: dict[tuple[str, str], Mapping[str, Any]] = {}
        for relative_path in files:
            file_path = _safe_child(root, relative_path)
            document = _read_object(file_path)
            if document.get("schema") != "xiuxian.content":
                raise ContentError(f"invalid content schema: {file_path}")
            if document.get("schema_version") != 1:
                raise ContentError(f"unsupported schema version: {file_path}")
            if document.get("content_version") != manifest["content_version"]:
                raise ContentError(f"content version mismatch: {file_path}")
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

        return cls(root=root, manifest=copy.deepcopy(manifest), _records=records)

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


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContentError(f"content file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContentError(f"invalid JSON: {path}: {exc.msg}") from exc
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


__all__ = ["ContentBundle", "ContentError"]
