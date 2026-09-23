"""Pure rules for the v0.1 sect membership slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


SECT_CREATE_COST = 1_000
SECT_MAX_MEMBERS = 20
SECT_WAREHOUSE_CAPACITY = 50
SECT_APPLICATION_TTL_SECONDS = 24 * 60 * 60
SECT_JOIN_COOLDOWN_SECONDS = 24 * 60 * 60
SECT_CONTENT_VERSION = "content-0.1"
SECT_RULE_VERSION = "social-0.1.0"


class SectRole(StrEnum):
    MEMBER = "member"
    DEACON = "deacon"
    ELDER = "elder"
    VICE_LEADER = "vice_leader"
    LEADER = "leader"


MANAGEMENT_ROLES = frozenset({SectRole.ELDER, SectRole.VICE_LEADER, SectRole.LEADER})
LEADER_ROLES = frozenset({SectRole.VICE_LEADER, SectRole.LEADER})
SECT_NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff-]{2,24}$", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SectDefinition:
    max_members: int = SECT_MAX_MEMBERS
    warehouse_capacity: int = SECT_WAREHOUSE_CAPACITY
    create_cost: int = SECT_CREATE_COST
    application_ttl_seconds: int = SECT_APPLICATION_TTL_SECONDS
    content_version: str = SECT_CONTENT_VERSION
    rule_version: str = SECT_RULE_VERSION


SECT_DEFINITION = SectDefinition()


def normalize_sect_name(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_sect_name_key(value: str) -> str:
    return normalize_sect_name(value).casefold()


def validate_sect_name(value: str) -> str:
    name = normalize_sect_name(value)
    if not SECT_NAME_PATTERN.fullmatch(name):
        raise ValueError("sect name must be 2-24 letters, numbers, CJK characters or hyphens")
    return name


def validate_sect_motto(value: str) -> str:
    motto = " ".join(value.strip().split())
    if len(motto) > 80:
        raise ValueError("sect motto is too long")
    return motto


def role_label(value: str) -> str:
    labels = {
        SectRole.MEMBER: "成员",
        SectRole.DEACON: "执事",
        SectRole.ELDER: "长老",
        SectRole.VICE_LEADER: "副宗主",
        SectRole.LEADER: "宗主",
    }
    try:
        return labels.get(SectRole(value), value)
    except ValueError:
        return value


__all__ = [
    "LEADER_ROLES",
    "MANAGEMENT_ROLES",
    "SECT_APPLICATION_TTL_SECONDS",
    "SECT_CONTENT_VERSION",
    "SECT_CREATE_COST",
    "SECT_DEFINITION",
    "SECT_JOIN_COOLDOWN_SECONDS",
    "SECT_MAX_MEMBERS",
    "SECT_RULE_VERSION",
    "SECT_WAREHOUSE_CAPACITY",
    "SectDefinition",
    "SectRole",
    "normalize_sect_name",
    "normalize_sect_name_key",
    "role_label",
    "validate_sect_motto",
    "validate_sect_name",
]
