"""Runtime configuration with conservative defaults for a local deployment."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .routine.rules import RedemptionCodeDefinition, redemption_codes_from_config

_QQ_CAPABILITIES = frozenset({"reference", "markdown", "keyboard", "media"})


def _positive_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _qq_capabilities_from_config(
    raw: str | None,
) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    if raw is None or not raw.strip():
        return None
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("XIUXIAN3_QQ_CAPABILITIES must be valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("XIUXIAN3_QQ_CAPABILITIES must be an object keyed by AppID")

    entries: list[tuple[str, tuple[str, ...]]] = []
    for app_id, declared in document.items():
        if (
            not isinstance(app_id, str)
            or not app_id.strip()
            or app_id != app_id.strip()
        ):
            raise ValueError("XIUXIAN3_QQ_CAPABILITIES AppID keys must be non-empty strings")
        if not isinstance(declared, list) or any(
            not isinstance(item, str) for item in declared
        ):
            raise ValueError("XIUXIAN3_QQ_CAPABILITIES values must be capability lists")
        unknown = set(declared) - _QQ_CAPABILITIES - {"text"}
        if unknown:
            raise ValueError(
                "XIUXIAN3_QQ_CAPABILITIES has unknown capabilities: "
                + ", ".join(sorted(unknown))
            )
        capabilities = tuple(
            item
            for item in ("reference", "markdown", "keyboard", "media")
            if item in declared
        )
        entries.append((app_id.strip(), capabilities))
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class XiuxianSettings:
    data_dir: Path = Path("data")
    database_name: str = "xiuxian3.sqlite3"
    busy_timeout_ms: int = 5_000
    max_inflight: int = 256
    redemption_codes: tuple[RedemptionCodeDefinition, ...] = ()
    billing_public_key: str = ""
    qq_capabilities_by_app_id: tuple[tuple[str, tuple[str, ...]], ...] | None = None

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name

    def qq_capabilities_for(self, app_id: str) -> tuple[str, ...] | None:
        if self.qq_capabilities_by_app_id is None:
            return None
        configured = dict(self.qq_capabilities_by_app_id)
        return ("text", *configured[app_id]) if app_id in configured else ("text",)

    @classmethod
    def from_env(cls, data_dir: str | Path | None = None) -> "XiuxianSettings":
        configured_dir = data_dir or os.getenv("XIUXIAN3_DATA_DIR", "data")
        return cls(
            data_dir=Path(configured_dir),
            database_name=os.getenv("XIUXIAN3_DATABASE_NAME", "xiuxian3.sqlite3"),
            busy_timeout_ms=_positive_int("XIUXIAN3_DB_BUSY_TIMEOUT_MS", 5_000),
            max_inflight=_positive_int("XIUXIAN3_MAX_INFLIGHT", 256),
            redemption_codes=redemption_codes_from_config(
                os.getenv("XIUXIAN3_REDEMPTION_CODES", "")
            ),
            billing_public_key=os.getenv("XIUXIAN3_BILLING_PUBLIC_KEY", ""),
            qq_capabilities_by_app_id=_qq_capabilities_from_config(
                os.getenv("XIUXIAN3_QQ_CAPABILITIES")
            ),
        )
