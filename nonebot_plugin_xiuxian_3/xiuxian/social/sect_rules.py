"""Pure rules for the sect membership slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .social_content import sect_rules_record

_SECT_RULES = sect_rules_record()

SECT_CREATE_COST = int(_SECT_RULES["create_cost"])
SECT_MAX_MEMBERS = int(_SECT_RULES["max_members"])
SECT_WAREHOUSE_CAPACITY = int(_SECT_RULES["warehouse_capacity"])
SECT_APPLICATION_TTL_SECONDS = int(_SECT_RULES["application_ttl_seconds"])
SECT_JOIN_COOLDOWN_SECONDS = int(_SECT_RULES["join_cooldown_seconds"])


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
    "SECT_CREATE_COST",
    "SECT_DEFINITION",
    "SECT_JOIN_COOLDOWN_SECONDS",
    "SECT_MAX_MEMBERS",
    "SECT_WAREHOUSE_CAPACITY",
    "SectDefinition",
    "SectRole",
    "normalize_sect_name",
    "normalize_sect_name_key",
    "role_label",
    "validate_sect_motto",
    "validate_sect_name",
]
