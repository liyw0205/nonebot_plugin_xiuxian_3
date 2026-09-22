"""Runtime configuration with conservative defaults for a local deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .routine.rules import RedemptionCodeDefinition, redemption_codes_from_config


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


@dataclass(frozen=True, slots=True)
class XiuxianSettings:
    data_dir: Path = Path("data")
    database_name: str = "xiuxian3.sqlite3"
    busy_timeout_ms: int = 5_000
    max_inflight: int = 256
    redemption_codes: tuple[RedemptionCodeDefinition, ...] = ()
    billing_public_key: str = ""

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name

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
        )
