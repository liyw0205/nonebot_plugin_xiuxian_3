"""Small helpers for decoding JSON values stored by repositories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def json_object(value: Any, default: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a detached mapping from a JSON value, or a detached default."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(default or {})


def json_list(value: Any, default: list[Any] | None = None) -> list[Any]:
    """Return a detached list from a JSON value, or a detached default."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = None
    if isinstance(value, list):
        return list(value)
    return list(default or [])


__all__ = ["json_list", "json_object"]
