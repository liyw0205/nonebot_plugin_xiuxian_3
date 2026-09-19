"""Deferred NoneBot integration seam for future command slices."""

from __future__ import annotations

from collections.abc import Mapping

from ...plugin import create_runtime
from ...bootstrap.lifecycle import Runtime


def build_runtime_for_nonebot(environ: Mapping[str, str] | None = None) -> Runtime:
    """Build the runtime; an actual NoneBot driver will be injected later."""

    return create_runtime(environ)