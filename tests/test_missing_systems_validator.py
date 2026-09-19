from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_content_docs.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("content_validator", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_systems_content_is_checked() -> None:
    validator = load_validator()
    errors: list[str] = []

    validator.check_missing_systems(errors)

    assert errors == []
