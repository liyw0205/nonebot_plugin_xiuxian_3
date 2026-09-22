"""Pure player rules used by application services."""

from __future__ import annotations

import hashlib


STAGE_NEW_USER = "new_user"
STAGE_MORTAL = "mortal"

QUALIFICATION_KEYS = (
    "body",
    "spirit",
    "insight",
    "root",
    "agility",
    "fortune",
)

QUALIFICATION_LABELS = {
    "body": "体魄",
    "spirit": "灵力",
    "insight": "悟性",
    "root": "根骨",
    "agility": "身法",
    "fortune": "气运",
}

STAGE_LABELS = {
    STAGE_NEW_USER: "新用户",
    STAGE_MORTAL: "凡人",
    "seeker": "求道者",
    "cultivator": "修行者",
    "suspended": "暂停中",
}

STATUS_LABELS = {
    "active": "正常",
    "suspended": "暂停中",
    "deleted": "已删除",
}

LOCATION_LABELS = {
    "xuantian.new_town": "玄天界·新手城",
    "xuantian.outskirts": "玄天界·近郊",
    "xuantian.wilderness": "玄天界·近郊荒野",
    "xuantian.spirit_field": "玄天界·灵泉谷",
    "cave.mist_grotto": "雾隐洞天·一层",
    "xuantian.cloud_city": "玄天界·云城",
    "xuantian.array_hall": "玄天界·阵堂",
    "xuantian.domain_front": "玄天界·领域前线",
    "cave.ancient_domain": "远古洞天",
    "demon.abyss_depths": "魔渊深层",
    "beast.ancestral_lake": "祖灵湖",
    "void.portal": "虚空门户",
    "void.first_route": "虚空第一航道",
    "void.archive_ruins": "虚空档案遗迹",
    "void.sect_fortress": "虚空堡垒",
    "cave.time_garden": "时序福地",
    "void.void_market": "虚空集市",
}

REALM_LABELS = {
    "mortal": "凡人",
    "qi_sensing": "感气",
    "qi_gathering": "聚气",
    "foundation": "筑基",
    "golden_core": "金丹",
    "nascent_soul": "元婴",
    "soul_transformation": "化神",
    "void_refining": "炼虚",
}

DAO_NAME_MAX_LENGTH = 7


def normalize_dao_name(value: str) -> str:
    return value.strip()


def validate_dao_name(value: str, *, allow_empty: bool = False) -> str:
    normalized = normalize_dao_name(value)
    if not normalized and allow_empty:
        return normalized
    if not normalized:
        raise ValueError("dao name cannot be empty")
    if len(normalized) > DAO_NAME_MAX_LENGTH:
        raise ValueError("dao name is too long")
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise ValueError("dao name contains whitespace or control characters")
    return normalized


def qualification_for(platform: str, platform_user_id: str) -> dict[str, int]:
    """Generate a stable six-stat snapshot with values 5..15 and sum 60."""

    digest = hashlib.blake2b(
        f"{platform}\x00{platform_user_id}".encode("utf-8"), digest_size=8
    ).digest()
    offsets = [(byte % 11) - 5 for byte in digest[:3]]
    values = [10 + offsets[0], 10 + offsets[1], 10 + offsets[2]]
    values.extend(10 - offset for offset in offsets)
    return dict(zip(QUALIFICATION_KEYS, values, strict=True))


def validate_qualification(value: dict[str, int]) -> None:
    if tuple(value) != QUALIFICATION_KEYS:
        raise ValueError("qualification keys are invalid")
    if any(not isinstance(item, int) or not 5 <= item <= 15 for item in value.values()):
        raise ValueError("qualification values are out of range")
    if sum(value.values()) != 60:
        raise ValueError("qualification total must be 60")
