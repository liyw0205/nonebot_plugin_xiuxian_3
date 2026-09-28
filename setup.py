"""Build hook that bundles the repository content pack into the wheel.

The source tree keeps ``data/`` at the repository root so operators can edit
and mount it.  A normal wheel cannot include files outside a Python package,
so the build step copies only JSON content into the installed package.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copy2

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        source_root = Path(__file__).resolve().parent / "data"
        target_root = Path(self.build_lib) / "nonebot_plugin_xiuxian_3" / "data"
        for source in source_root.rglob("*.json"):
            target = target_root / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy2(source, target)


setup(cmdclass={"build_py": build_py})
