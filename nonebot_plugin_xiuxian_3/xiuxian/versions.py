"""Active content version helpers.

Historical rule modules intentionally keep the version that produced an old
operation snapshot.  New runtime code should use this module instead of
copying the documentation release number into a business rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from .content import ContentBundle


def bundled_content(data_dir: str | Path | None = None) -> ContentBundle | None:
    if data_dir is not None:
        return ContentBundle.load_optional(Path(data_dir).expanduser())
    candidates = (
        Path(__file__).resolve().parents[1] / "data",
        Path(__file__).resolve().parents[2] / "data",
    )
    for root in candidates:
        bundle = ContentBundle.load_optional(root)
        if bundle is not None:
            return bundle
    return None


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


def module_versions(module_name: str, *, fallback: tuple[str, str] = ("current", "current")) -> tuple[str, str]:
    """Return a module's compatibility snapshot from the central metadata file."""

    bundle = bundled_content()
    if bundle is None:
        return fallback
    # ContentBundle keeps metadata private; loading through the public helper
    # avoids putting release labels back into rule modules.
    metadata_path = bundle.root / str(bundle.manifest.get("metadata", "内容版本.json"))
    try:
        import json

        metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        value = metadata.get("modules", {}).get(module_name)
    except (OSError, ValueError, TypeError):
        value = None
    if isinstance(value, list) and len(value) == 2 and all(isinstance(item, str) for item in value):
        return value[0], value[1]
    return fallback


def module_content_version(module_name: str, *, fallback: str = "current") -> str:
    return module_versions(module_name, fallback=(fallback, "current"))[0]


def module_rule_version(module_name: str, *, fallback: str = "current") -> str:
    return module_versions(module_name, fallback=("current", fallback))[1]


def content_key(name: str, *, fallback: str | None = None) -> str:
    """Resolve a stable content/random-pool key from central metadata."""

    bundle = bundled_content()
    if bundle is not None:
        metadata_path = bundle.root / str(bundle.manifest.get("metadata", "内容版本.json"))
        try:
            import json

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            value = metadata.get("pools", {}).get(name)
            if isinstance(value, str) and value:
                return value
        except (OSError, ValueError, TypeError):
            pass
    return fallback if fallback is not None else name


__all__ = [
    "active_content_version",
    "active_rule_version",
    "bundled_content",
    "content_key",
    "module_content_version",
    "module_rule_version",
    "module_versions",
]
