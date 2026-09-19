"""The only plugin entry point; construction is explicit and side-effect-free."""

from __future__ import annotations

from collections.abc import Mapping

from .bootstrap.config import RuntimeConfig
from .bootstrap.composition import build_runtime
from .bootstrap.lifecycle import Runtime


def create_runtime(environ: Mapping[str, str] | None = None) -> Runtime:
    """Build a runtime without starting it or registering platform handlers."""

    return build_runtime(RuntimeConfig.from_env(environ))


__all__ = ["create_runtime"]