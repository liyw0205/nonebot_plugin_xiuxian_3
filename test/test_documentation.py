"""Keep repository documentation entry points free of broken local links."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
DOCUMENT_ROOTS = (ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "docs")


def _markdown_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for path in DOCUMENT_ROOTS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.md"))
    return tuple(sorted(files))


def _local_target(value: str) -> str | None:
    target = value.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split("#", 1)[0]
    if not target or "://" in target or target.startswith(("mailto:", "tel:")):
        return None
    return target


def test_local_markdown_links_resolve_within_the_repository() -> None:
    broken: list[str] = []
    for source in _markdown_files():
        for match in MARKDOWN_LINK.finditer(source.read_text(encoding="utf-8")):
            target = _local_target(match.group(1))
            if target is None:
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                broken.append(f"{source.relative_to(ROOT)} -> {target}")
    assert not broken, "Broken local Markdown links:\n" + "\n".join(broken)
