"""Local readiness checks for the core runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class HealthStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    status: HealthStatus
    detail: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    ready: bool
    checks: tuple[HealthCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [
                {"name": check.name, "status": check.status.value, "detail": check.detail}
                for check in self.checks
            ],
        }


def local_health(*, started: bool, data_dir: Path, activated_features: tuple[str, ...]) -> HealthReport:
    checks = (
        HealthCheck(
            "runtime",
            HealthStatus.PASS if started else HealthStatus.FAIL,
            "started" if started else "not started",
        ),
        HealthCheck(
            "data_dir",
            HealthStatus.PASS if data_dir.is_dir() else HealthStatus.FAIL,
            str(data_dir),
        ),
        HealthCheck(
            "feature_registry",
            HealthStatus.PASS,
            f"{len(activated_features)} feature(s) active",
        ),
    )
    return HealthReport(ready=all(check.status is HealthStatus.PASS for check in checks), checks=checks)