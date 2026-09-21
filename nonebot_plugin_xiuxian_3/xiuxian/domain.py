"""Compatibility exports for domain rules split by feature."""

from .player.rules import (
    QUALIFICATION_KEYS,
    STAGE_MORTAL,
    STAGE_NEW_USER,
    qualification_for,
    validate_qualification,
)

__all__ = [
    "QUALIFICATION_KEYS",
    "STAGE_MORTAL",
    "STAGE_NEW_USER",
    "qualification_for",
    "validate_qualification",
]
