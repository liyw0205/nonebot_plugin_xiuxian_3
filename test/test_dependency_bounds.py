"""Keep direct plugin requirements open to newer compatible releases."""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def test_project_dependencies_do_not_cap_versions() -> None:
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    groups = {
        "build": config.get("build-system", {}).get("requires", []),
        "base": project.get("dependencies", []),
        **project.get("optional-dependencies", {}),
    }
    for group, dependencies in groups.items():
        for dependency in dependencies:
            requirement = Requirement(dependency)
            assert not any(
                spec.operator in {"<", "<=", "==", "===", "~="}
                for spec in requirement.specifier
            ), f"{group}: {dependency}"
