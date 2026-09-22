"""Pure rules for the three mortal onboarding lessons."""

from __future__ import annotations

from collections.abc import Iterable


GUIDE_READ_WORLD = "guide.read_world"
GUIDE_GATHER_BLOOD_GRASS = "guide.gather_blood_grass"
GUIDE_CHOOSE_SERVICE = "guide.choose_service"
INTRO_GUIDES = (
    GUIDE_READ_WORLD,
    GUIDE_GATHER_BLOOD_GRASS,
    GUIDE_CHOOSE_SERVICE,
)

GUIDE_LABELS = {
    GUIDE_READ_WORLD: "阅读世界说明",
    GUIDE_GATHER_BLOOD_GRASS: "教学采集",
    GUIDE_CHOOSE_SERVICE: "生产教学",
}

GUIDE_COMMANDS = {
    GUIDE_READ_WORLD: "阅读",
    GUIDE_GATHER_BLOOD_GRASS: "采集",
    GUIDE_CHOOSE_SERVICE: "炼丹",
}

SERVICE_LABELS = {
    "alchemy": "炼丹",
    "artifice": "炼器",
    "formation": "布阵",
    "cooking": "烹饪",
}

GUIDE_ALIASES = {
    "阅读": GUIDE_READ_WORLD,
    "世界": GUIDE_READ_WORLD,
    "阅读世界": GUIDE_READ_WORLD,
    "采集": GUIDE_GATHER_BLOOD_GRASS,
    "止血草": GUIDE_GATHER_BLOOD_GRASS,
    "教学采集": GUIDE_GATHER_BLOOD_GRASS,
    "服务": GUIDE_CHOOSE_SERVICE,
    "生产": GUIDE_CHOOSE_SERVICE,
    "炼丹": GUIDE_CHOOSE_SERVICE,
    "炼器": GUIDE_CHOOSE_SERVICE,
    "布阵": GUIDE_CHOOSE_SERVICE,
    "烹饪": GUIDE_CHOOSE_SERVICE,
}

SERVICE_ALIASES = {
    "炼丹": "alchemy",
    "炼器": "artifice",
    "布阵": "formation",
    "alchemy": "alchemy",
    "artifice": "artifice",
    "formation": "formation",
    "烹饪": "cooking",
    "cooking": "cooking",
}

TRAVEL_DESTINATIONS = {
    "近郊": "xuantian.outskirts",
    "玄天近郊": "xuantian.outskirts",
    "xuantian.outskirts": "xuantian.outskirts",
    "新手城": "xuantian.new_town",
    "青石镇": "xuantian.new_town",
    "xuantian.new_town": "xuantian.new_town",
    "灵泉谷": "xuantian.spirit_field",
    "玄天灵泉谷": "xuantian.spirit_field",
    "xuantian.spirit_field": "xuantian.spirit_field",
}

TRAVEL_LABELS = {
    "xuantian.outskirts": "玄天近郊",
    "xuantian.new_town": "青石镇",
    "xuantian.spirit_field": "灵泉谷",
}

TRAVEL_COSTS = {
    "xuantian.outskirts": 2,
    "xuantian.new_town": 1,
    "xuantian.spirit_field": 4,
}


def resolve_guide(value: str) -> str | None:
    normalized = value.strip()
    if normalized in INTRO_GUIDES:
        return normalized
    return GUIDE_ALIASES.get(normalized)


def resolve_service(value: str) -> str | None:
    return SERVICE_ALIASES.get(value.strip())


def resolve_destination(value: str) -> str | None:
    return TRAVEL_DESTINATIONS.get(value.strip())


def intro_complete(flags: Iterable[str]) -> bool:
    completed = set(flags)
    return all(key in completed for key in INTRO_GUIDES)


def validate_service(value: str) -> str:
    if value not in SERVICE_LABELS:
        raise ValueError("unsupported teaching service")
    return value
