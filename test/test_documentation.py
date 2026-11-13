"""Keep repository documentation entry points free of broken local links."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
DOCUMENT_ROOTS = (ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "AGENTS.md", ROOT / "docs")


def _markdown_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for path in DOCUMENT_ROOTS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in path.rglob("*.md")
                if candidate.relative_to(ROOT).parts[:2] != ("docs", "goals")
            )
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


def test_public_documentation_entry_points_are_present() -> None:
    required = (
        ROOT / "README.md",
        ROOT / "docs/index.md",
        ROOT / "docs/installation.md",
        ROOT / "docs/usage.md",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, "Public documentation entry points are missing:\n" + "\n".join(missing)


def test_player_copywriting_contract_excludes_mixed_development_tone() -> None:
    copywriting = (ROOT / "docs/messaging-copywriting.md").read_text(encoding="utf-8")
    assert "## 文案风格" in copywriting
    assert "不要把半段" in copywriting
    assert "不把开发进度写成世界设定" in copywriting
    assert "请等待后续更新" not in copywriting


def test_published_docs_do_not_link_to_local_support_files() -> None:
    forbidden = ("docs/goals/", ".codex-")
    linked: list[str] = []
    for source in _markdown_files():
        content = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(content):
            target = match.group(1)
            if any(part in target for part in forbidden):
                linked.append(f"{source.relative_to(ROOT)} -> {target}")
    assert not linked, "Published docs must not link local support files:\n" + "\n".join(linked)


def test_source_distribution_excludes_local_goals() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune docs/goals" in manifest
