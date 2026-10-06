"""Immutable transport models for the character attribute domain."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime
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
            "source_refs": [deepcopy(item) for item in self.source_refs],
            "formula_fingerprint": self.formula_fingerprint,
            "purpose": self.purpose,
            "created_at": self.created_at,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StatSnapshot":
        if not isinstance(payload, Mapping):
            raise StatSnapshotError("属性快照结构无效。")
        required = (
            "snapshot_id", "player_id", "base_stats", "path_stats", "derived_stats",
            "source_refs", "formula_fingerprint", "purpose", "created_at",
        )
        if any(key not in payload for key in required):
            raise StatSnapshotError("属性快照缺少必要字段。")
        try:
            from .rules import DERIVED_KEYS, STAT_KEYS

            snapshot_id = _text(payload["snapshot_id"])
            player_id = payload["player_id"]
            if type(player_id) is not int or player_id <= 0:
                raise ValueError("player_id must be a positive integer")
            base_stats = _integer_map(payload["base_stats"])
            if set(base_stats) != set(STAT_KEYS) or sum(base_stats.values()) != 60 or any(not 5 <= value <= 15 for value in base_stats.values()):
                raise ValueError("base stats must contain six valid qualifications")
            path_stats = _integer_map(payload["path_stats"])
            derived_stats = _integer_map(payload["derived_stats"])
            if set(derived_stats) != set(DERIVED_KEYS) or derived_stats["max_hp"] <= 0 or derived_stats["attack"] <= 0:
                raise ValueError("derived stat snapshot is incomplete")
            if not isinstance(payload["source_refs"], (list, tuple)) or not payload["source_refs"]:
                raise ValueError("stat snapshot sources are missing")
            source_refs = tuple(_source_ref(item) for item in payload["source_refs"])
            source_keys = [source["key"] for source in source_refs]
            if any(source_keys.count(key) != 1 for key in ("realm", "qualification", "permanent")):
                raise ValueError("stat snapshot base sources are incomplete or repeated")
            qualification_source = next(source for source in source_refs if source["key"] == "qualification")
            if _integer_map(qualification_source["value"]) != base_stats:
                raise ValueError("qualification source does not match base stats")
            permanent_source = next(source for source in source_refs if source["key"] == "permanent")
            permanent = _integer_map(permanent_source["value"])
            if set(permanent) != {"max_hp", "max_mp", "initiative", "carry_capacity", "exploration_rate_bp"} or permanent != permanent_source["effect"]:
                raise ValueError("permanent stat source is incomplete")
            formula_fingerprint = _text(payload["formula_fingerprint"])
            if len(formula_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in formula_fingerprint):
                raise ValueError("invalid stat formula fingerprint")
            purpose = _text(payload["purpose"])
            created_at = _text(payload["created_at"])
            if datetime.fromisoformat(created_at).tzinfo is None:
                raise ValueError("stat snapshot timestamp must have a timezone")
        except (TypeError, ValueError, KeyError) as exc:
            raise StatSnapshotError("属性快照字段无效。") from exc
        return cls(snapshot_id, player_id, base_stats, path_stats, derived_stats, source_refs, formula_fingerprint, purpose, created_at)


def _integer_map(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TypeError("stat map must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or type(item) is not int or item < 0:
            raise ValueError("stat values must be non-negative integers")
        result[key] = item
    return result


def _source_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("source reference must be an object")
    _text(value["key"])
    if value["multiplier_zone"] not in {"base", "path", "build", "environment", "temporary"}:
        raise ValueError("invalid source multiplier zone")
    value["value"]
    if "effect" in value:
        _integer_map(value["effect"])
    return deepcopy(dict(value))


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stat snapshot text must be non-empty")
    return value


__all__ = ["StatSnapshot", "StatSnapshotError"]
