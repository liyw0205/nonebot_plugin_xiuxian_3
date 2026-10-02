"""Immutable transport models for the character attribute domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class StatSnapshotError(ValueError):
    """Persisted attribute snapshot data does not satisfy its contract."""

    code = "STAT_SNAPSHOT_INVALID"


@dataclass(frozen=True, slots=True)
class StatSnapshot:
    snapshot_id: str
    player_id: int
    base_stats: dict[str, int]
    path_stats: dict[str, int]
    derived_stats: dict[str, int]
    source_refs: tuple[dict[str, Any], ...]
    formula_fingerprint: str
    purpose: str
    created_at: str
    already_completed: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "player_id": self.player_id,
            "base_stats": dict(self.base_stats),
            "path_stats": dict(self.path_stats),
            "derived_stats": dict(self.derived_stats),
            "source_refs": [dict(item) for item in self.source_refs],
            "formula_fingerprint": self.formula_fingerprint,
            "purpose": self.purpose,
            "created_at": self.created_at,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StatSnapshot":
        if not isinstance(payload, Mapping):
            raise StatSnapshotError("属性快照结构无效。")
        required = ("snapshot_id", "player_id", "base_stats", "derived_stats", "formula_fingerprint", "created_at")
        if any(key not in payload for key in required):
            raise StatSnapshotError("属性快照缺少必要字段。")
        try:
            snapshot_id = str(payload["snapshot_id"])
            player_id = int(payload["player_id"])
            base_stats = _integer_map(payload["base_stats"])
            path_stats = _integer_map(payload.get("path_stats", {}))
            derived_stats = _integer_map(payload["derived_stats"])
            source_refs = tuple(_source_ref(item) for item in payload.get("source_refs", ()))
            formula_fingerprint = str(payload["formula_fingerprint"])
            purpose = str(payload.get("purpose", ""))
            created_at = str(payload["created_at"])
        except (TypeError, ValueError, KeyError) as exc:
            raise StatSnapshotError("属性快照字段无效。") from exc
        if not snapshot_id or player_id <= 0 or not formula_fingerprint or not created_at:
            raise StatSnapshotError("属性快照字段无效。")
        return cls(snapshot_id, player_id, base_stats, path_stats, derived_stats, source_refs, formula_fingerprint, purpose, created_at)


def _integer_map(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TypeError("stat map must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            raise ValueError("boolean is not an integer stat")
        result[str(key)] = int(item)
    return result


def _source_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("source reference must be an object")
    return dict(value)


__all__ = ["StatSnapshot", "StatSnapshotError"]
