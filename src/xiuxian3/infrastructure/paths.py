"""Runtime data-root and path traversal boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class PathBoundaryError(ValueError):
    """Raised when a path would leave the configured runtime root."""


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @classmethod
    def from_root(cls, root: Path) -> "RuntimePaths":
        return cls(root=Path(root).expanduser().resolve())

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("backups", "cache", "logs", "migrations", "tmp"):
            self.resolve(name).mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str | Path) -> Path:
        candidate_input = Path(relative)
        if candidate_input.is_absolute():
            raise PathBoundaryError("absolute paths are not accepted")
        if any(part in {"", ".", ".."} for part in candidate_input.parts):
            raise PathBoundaryError("path must be a clean relative path")
        if "\x00" in str(relative):
            raise PathBoundaryError("NUL bytes are not accepted")
        candidate = (self.root / candidate_input).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathBoundaryError("path escapes the runtime data root") from exc
        if os.path.commonpath((str(self.root), str(candidate))) != str(self.root):
            raise PathBoundaryError("path escapes the runtime data root")
        return candidate