"""Active content version helpers.

Historical rule modules intentionally keep the version that produced an old
operation snapshot.  New runtime code should use this module instead of
copying the documentation release number into a business rule.
"""

from __future__ import annotations

from pathlib import Path
from .content import ContentBundle


def bundled_content(data_dir: str | Path | None = None) -> ContentBundle | None:
    root = Path(data_dir).expanduser() if data_dir is not None else Path(__file__).resolve().parents[2] / "data"
    return ContentBundle.load_optional(root)


def active_content_version(data_dir: str | Path | None = None, *, fallback: str = "content-0") -> str:
    bundle = bundled_content(data_dir)
    return bundle.content_version if bundle is not None else fallback


def active_rule_version(
    data_dir: str | Path | None = None,
    *,
    kind: str | None = None,
    key: str | None = None,
    fallback: str = "rules-0",
) -> str:
    bundle = bundled_content(data_dir)
    if bundle is None:
        return fallback
    if kind and key:
        row = bundle.get(kind, key)
        if row is not None and isinstance(row.get("rule_version"), str):
            return row["rule_version"]
    return bundle.rule_version


__all__ = ["active_content_version", "active_rule_version", "bundled_content"]
