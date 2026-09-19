"""Serializable success and error values shared by all application use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, Mapping, TypeVar, cast


class ErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    CONFLICT = "conflict"
    COOLDOWN = "cooldown"
    INSUFFICIENT_RESOURCE = "insufficient_resource"
    PLAYER_STAGE_CONFLICT = "player_stage_conflict"
    SEEKING_ALREADY_DONE = "seeking_already_done"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class Error:
    code: ErrorCode
    message: str
    retryable: bool = False
    fields: Mapping[str, str] = field(default_factory=dict)


T = TypeVar("T")
_UNSET = object()


@dataclass(frozen=True, slots=True, init=False)
class Result(Generic[T]):
    value: T | None = None
    error: Error | None = None

    def __init__(self, value: object = _UNSET, error: Error | None = None) -> None:
        has_value = value is not _UNSET
        if has_value == (error is not None):
            raise ValueError("Result must contain exactly one of value or error")
        object.__setattr__(self, "value", cast(T | None, value) if has_value else None)
        object.__setattr__(self, "error", error)

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return cls(value=value)

    @classmethod
    def failure(cls, error: Error) -> "Result[T]":
        return cls(error=error)