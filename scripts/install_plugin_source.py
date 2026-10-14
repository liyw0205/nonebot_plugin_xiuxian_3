#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path

PLUGIN_NAME = "nonebot_plugin_xiuxian_3"
PLUGIN_DIR = Path("src/plugins")


def _table_bounds(lines: list[str], table: str) -> tuple[int, int] | None:
    header = re.compile(rf"^\s*\[{re.escape(table)}\]\s*(?:#.*)?(?:\r?\n)?$")
    table_start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if table_start is None:
        return None
    table_end = len(lines)
    for i in range(table_start + 1, len(lines)):
        if re.match(r"^\s*\[", lines[i]):
            table_end = i
            break
    return table_start, table_end


def _array_end(lines: list[str], start: int, value_start: int) -> tuple[int, int]:
    depth = 0
    quote = ""
    escaped = False
    opened = False
    for line_index in range(start, len(lines)):
        line = lines[line_index]
        begin = value_start if line_index == start else 0
        for offset in range(begin, len(line)):
            char = line[offset]
            if quote:
                if quote == '"' and escaped:
                    escaped = False
                elif quote == '"' and char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char == "#":
                break
            if char in ('"', "'"):
                quote = char
            elif char == "[":
                depth += 1
                opened = True
            elif char == "]" and opened:
                depth -= 1
                if depth == 0:
                    return line_index, offset + 1
    raise ValueError("无法定位 pyproject.toml 数组结尾")


def _set_array(text: str, table: str, key_pattern: str, key: str, values: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    bounds = _table_bounds(lines, table)
    if bounds is None:
        newline = "\r\n" if "\r\n" in text else "\n"
        if text and not text.endswith(("\n", "\r")):
            text += newline
        if text and not text.endswith(newline * 2):
            text += newline
        return text + f"[{table}]{newline}{key} = {_format_array(values)}{newline}"

    table_start, table_end = bounds
    assignment = re.compile(rf"^\s*{key_pattern}\s*=")
    value_line = next((i for i in range(table_start + 1, table_end) if assignment.match(lines[i])), None)
    rendered = _format_array(values)
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    if value_line is None:
        lines.insert(table_start + 1, f"{key} = {rendered}{newline}")
        return "".join(lines)

    equal_at = lines[value_line].index("=")
    whitespace_end = equal_at + 1
    while whitespace_end < len(lines[value_line]) and lines[value_line][whitespace_end].isspace():
        whitespace_end += 1
    end_line, end_column = _array_end(lines, value_line, whitespace_end)
    replacement = lines[value_line][:whitespace_end] + rendered + lines[end_line][end_column:]
    lines[value_line : end_line + 1] = [replacement]
    return "".join(lines)


def _format_array(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value, ensure_ascii=False) for value in values) + "]"


def _updated_pyproject(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    parsed = tomllib.loads(original)
    nonebot = parsed.get("tool", {}).get("nonebot", {})
    plugin_dirs = nonebot.get("plugin_dirs", [])
    if not isinstance(plugin_dirs, list) or any(not isinstance(item, str) for item in plugin_dirs):
        raise ValueError("tool.nonebot.plugin_dirs 必须是字符串数组")

    updated = original
    if str(PLUGIN_DIR) not in plugin_dirs:
        updated = _set_array(
            updated,
            "tool.nonebot",
            r"plugin_dirs",
            "plugin_dirs",
            [*plugin_dirs, str(PLUGIN_DIR)],
        )

    local_plugins = nonebot.get("plugins", {}).get("@local", [])
    if not isinstance(local_plugins, list) or any(not isinstance(item, str) for item in local_plugins):
        raise ValueError('tool.nonebot.plugins["@local"] 必须是字符串数组')
    if PLUGIN_NAME in local_plugins:
        updated = _set_array(
            updated,
            "tool.nonebot.plugins",
            r'(?:"@local"|\'@local\'|@local)',
            '"@local"',
            [item for item in local_plugins if item != PLUGIN_NAME],
        )

    result = tomllib.loads(updated)
    configured_dirs = result.get("tool", {}).get("nonebot", {}).get("plugin_dirs", [])
    configured_plugins = result.get("tool", {}).get("nonebot", {}).get("plugins", {}).get("@local", [])
    if str(PLUGIN_DIR) not in configured_dirs or PLUGIN_NAME in configured_plugins:
        raise ValueError("无法将宿主 pyproject.toml 切换为本地插件目录加载")
    return updated


def _atomic_write(path: Path, content: str) -> Path:
    return _atomic_bytes(path, content.encode("utf-8"))


def _atomic_bytes(path: Path, content: bytes) -> Path:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.new-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _seed_plan(source: Path, target: Path) -> tuple[list[tuple[Path, bytes]], list[str]]:
    manifest = json.loads(Path(__file__).with_name("seed_migrations.json").read_text(encoding="utf-8"))
    changes: list[tuple[Path, bytes]] = []
    custom: list[str] = []
    for seed in sorted(source.rglob("*.json")):
        relative = seed.relative_to(source)
        destination = target / "data" / relative
        if seed.is_symlink() or destination.is_symlink() or not destination.resolve().is_relative_to((target / "data").resolve()):
            raise ValueError(f"种子路径不能指向 data 目录以外：{relative}")
        new = seed.read_bytes()
        json.loads(new)
        if not destination.exists():
            changes.append((relative, new))
            continue
        old = destination.read_bytes()
        if old == new:
            continue
        rule = manifest.get(relative.as_posix())
        if rule and hashlib.sha256(old).hexdigest() in rule["old_sha256"]:
            if hashlib.sha256(new).hexdigest() != rule["new_sha256"]:
                raise ValueError(f"官方种子迁移目标指纹不匹配：{relative}")
            changes.append((relative, new))
        else:
            custom.append(relative.as_posix())
    return changes, custom


def install(
    source: Path | None, target: Path, *, data_source: Path | None = None,
    validate_after: bool = False,
) -> None:
    target = target.resolve()
    source = source.resolve() if source is not None else None
    if source is not None and not (source / "__init__.py").is_file():
        raise ValueError(f"插件源码缺少入口文件：{source / '__init__.py'}")

    pyproject = target / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError(f"宿主缺少 pyproject.toml：{pyproject}")
    updated_pyproject = _updated_pyproject(pyproject) if source is not None else None
    changes, custom = _seed_plan(data_source.resolve(), target) if data_source else ([], [])

    plugin_parent = target / PLUGIN_DIR
    plugin_parent.mkdir(parents=True, exist_ok=True)
    plugin_target = plugin_parent / PLUGIN_NAME
    staging = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}.new-", dir=plugin_parent)) if source else None
    backup_root = (target / "data" if source is None else target) / ".xiuxian3/backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"deploy-{uuid.uuid4().hex}"
    backup.mkdir(mode=0o700)
    shutil.copy2(pyproject, backup / "pyproject.toml")
    for relative, _ in changes:
        old = target / "data" / relative
        if old.exists():
            saved = backup / "data" / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, saved)
    journal = {"status": "pending", "data_files": [str(path) for path, _ in changes]}
    journal_path = backup / "deployment.json"
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"部署备份：{backup}", flush=True)
    pyproject_staging: Path | None = None
    moved_old = False
    installed_new = False
    applied: list[Path] = []
    try:
        if source is not None:
            shutil.copytree(
                source, staging, dirs_exist_ok=True, symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            pyproject_staging = _atomic_write(pyproject, updated_pyproject)
            if plugin_target.exists() or plugin_target.is_symlink():
                os.replace(plugin_target, backup / PLUGIN_NAME)
                moved_old = True
            os.replace(staging, plugin_target)
            installed_new = True
            os.replace(pyproject_staging, pyproject)
            pyproject_staging = None
        for relative, new in changes:
            destination = target / "data" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = _atomic_bytes(destination, new)
            os.replace(temporary, destination)
            applied.append(relative)
            print(f"官方种子写入：{relative}", flush=True)
        if data_source is not None:
            files = sorted(path for path in (target / "data").rglob("*.json") if not path.is_relative_to(backup_root))
            if not files:
                raise ValueError("data 目录没有 JSON 内容")
            for path in files:
                try:
                    json.loads(path.read_bytes())
                except (ValueError, UnicodeError) as error:
                    raise ValueError(f"保留的 JSON 有语法冲突：{path.relative_to(target)}：{error}") from error
            print(f"事务内已校验 {len(files)} 个 JSON 文件", flush=True)
        if validate_after:
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--target", str(target), "--validate"],
                cwd=target, check=True,
                env={**os.environ, "XIUXIAN3_DATA_DIR": str(target / "data"), "PYTHONDONTWRITEBYTECODE": "1"},
            )
        journal["status"] = "complete"
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        for relative in reversed(applied):
            destination = target / "data" / relative
            saved = backup / "data" / relative
            if saved.exists():
                shutil.copy2(saved, destination)
            else:
                destination.unlink(missing_ok=True)
        if installed_new:
            _remove(plugin_target)
        if moved_old:
            os.replace(backup / PLUGIN_NAME, plugin_target)
        shutil.copy2(backup / "pyproject.toml", pyproject)
        journal["status"] = "rolled_back"
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("部署失败，源码、TOML 和种子已回退；.env/SQLite/自定义数据未覆盖。", file=sys.stderr)
        if custom:
            print("保留的自定义或未知种子如与新版本冲突，须人工合并后重试：" + ", ".join(custom), file=sys.stderr)
        raise
    finally:
        if staging is not None and staging.exists():
            _remove(staging)
        if pyproject_staging is not None:
            pyproject_staging.unlink(missing_ok=True)
    if source is not None:
        print(f"插件源码已部署至 {plugin_target}")
    if custom:
        print("保留自定义/未知种子：" + ", ".join(custom))
    print(f"种子更新 {len(changes)} 个；保留自定义/未知种子 {len(custom)} 个；备份保留在 {backup}")


def validate(target: Path) -> None:
    target = target.resolve()
    pyproject = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    config = pyproject.get("tool", {}).get("nonebot", {})
    plugin_dirs = config.get("plugin_dirs", [])
    if str(PLUGIN_DIR) not in plugin_dirs:
        raise ValueError(f"宿主未配置 plugin_dirs={str(PLUGIN_DIR)!r}")
    plugin_path = target / PLUGIN_DIR / PLUGIN_NAME
    if not (plugin_path / "__init__.py").is_file():
        raise ValueError(f"宿主插件入口不存在：{plugin_path / '__init__.py'}")

    os.chdir(target)
    sys.path.insert(0, str(target))
    sys.dont_write_bytecode = True
    import nonebot
    from nonebot.matcher import matchers as registered_matchers
    from nonebot.plugin import load_all_plugins

    nonebot.init()
    plugins = load_all_plugins([], plugin_dirs)
    expected_module = "src.plugins.nonebot_plugin_xiuxian_3"
    loaded = [plugin for plugin in plugins if plugin.module_name == expected_module]
    if len(loaded) != 1:
        raise ValueError(f"NoneBot 未从 {plugin_path} 加载插件")
    plugin = loaded[0]
    module_file = Path(plugin.module.__file__).resolve() if plugin.module.__file__ else None
    if module_file is None or plugin_path.resolve() not in module_file.parents:
        raise ValueError(f"插件模块路径不在宿主 src/plugins：{module_file}")
    if not plugin.matcher:
        raise ValueError("插件已加载但没有注册 matcher")
    if any(not matcher.handlers for matcher in plugin.matcher):
        raise ValueError("插件 matcher 没有注册 handler")
    registered = [
        matcher
        for group in registered_matchers.values()
        for matcher in group
        if matcher.plugin is plugin
    ]
    if len(registered) != len(plugin.matcher) or set(registered) != plugin.matcher:
        raise ValueError("插件 matcher 注册不一致或重复")
    handlers = sum(len(matcher.handlers) for matcher in plugin.matcher)
    # The story validators are lazy per story; exercise the recorded arcs against the
    # host data so stale or stubbed seeds fail the deploy gate instead of the runtime.
    # A host may legitimately load a stub or vendor source without the content module,
    # so the extra story check only applies when the real content module is importable.
    import importlib

    try:
        mainline = importlib.import_module(f"{expected_module}.xiuxian.adventures.mainline")
    except ModuleNotFoundError:
        mainline = None
    if mainline is not None:
        for story in (
            mainline.MAINLINE_STORY_KEY,
            mainline.DOMAIN_FRONTIER_STORY_KEY,
            mainline.VOID_ARCHIVE_STORY_KEY,
        ):
            mainline.mainline_definitions(story_key=story)
    print(
        f"NoneBot 已加载 {expected_module} "
        f"module_file={module_file} matchers={len(plugin.matcher)} handlers={handlers}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="部署或验证宿主中的 xiu3 本地插件源码")
    parser.add_argument("--source", type=Path, help="xiu3 仓库中的 nonebot_plugin_xiuxian_3 目录")
    parser.add_argument("--target", type=Path, required=True, help="NoneBot 宿主目录")
    parser.add_argument("--validate", action="store_true", help="使用宿主 plugin_dirs 实际验载")
    parser.add_argument("--data-source", type=Path, help="官方种子目录；仅迁移指纹表中的旧官方文件")
    parser.add_argument("--data-only", action="store_true", help="Docker 仅迁移种子，不替换已有源码/TOML")
    parser.add_argument("--validate-after-install", action="store_true", help="校验失败自动回退本次部署")
    args = parser.parse_args()
    if args.validate:
        validate(args.target)
    else:
        if args.source is None and not args.data_only:
            parser.error("部署模式必须传入 --source")
        if args.data_only and args.data_source is None:
            parser.error("--data-only 必须传入 --data-source")
        install(
            None if args.data_only else args.source, args.target,
            data_source=args.data_source, validate_after=args.validate_after_install,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tomllib.TOMLDecodeError, subprocess.CalledProcessError) as error:
        print(f"[xiuxian3] 插件部署失败：{error}", file=sys.stderr)
        raise SystemExit(1)
