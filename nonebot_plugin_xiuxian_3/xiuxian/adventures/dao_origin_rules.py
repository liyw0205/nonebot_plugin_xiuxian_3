"""Versioned contract for the v0.6 dao-origin solo secret realm."""

from __future__ import annotations


DAO_ORIGIN_KEY = "instance.secret_realm.dao_origin"
DAO_ORIGIN_LOCATION = "dao.origin_gate"
DAO_ORIGIN_PERMISSION = "access.dao.origin"
DAO_ORIGIN_STAMINA_COST = 60
DAO_ORIGIN_QUOTA_KEY = "lifetime"
DAO_ORIGIN_EXPIRY_SECONDS = 60 * 60
DAO_ORIGIN_CONTENT_VERSION = ""
DAO_ORIGIN_RULE_VERSION = ""
DAO_ORIGIN_STORY_FLAG = "story.dao_origin"
DAO_ORIGIN_CODEX = "codex.dao.service_origin"
DAO_ORIGIN_FIRST_REWARD = {DAO_ORIGIN_STORY_FLAG: 1, DAO_ORIGIN_CODEX: 1}
DAO_ORIGIN_REPEAT_REWARD: dict[str, int] = {}

DAO_ORIGIN_NODES = (
    "origin_threshold",
    "dao_spring",
    "three_realm_seal",
    "service_archive",
    "fruit_trace",
    "witness_platform",
    "origin_oath",
    "new_chapter_gate",
)

DAO_ORIGIN_NODE_LABELS = {
    "origin_threshold": "道源关隘",
    "dao_spring": "道源泉眼",
    "three_realm_seal": "三界校验印",
    "service_archive": "服务档案库",
    "fruit_trace": "道果痕迹",
    "witness_platform": "见证台",
    "origin_oath": "道源誓约",
    "new_chapter_gate": "新章门扉",
}

DAO_ORIGIN_NODE_ALIASES = {
    **{key: key for key in DAO_ORIGIN_NODES},
    **{label: key for key, label in DAO_ORIGIN_NODE_LABELS.items()},
    **{str(index + 1): key for index, key in enumerate(DAO_ORIGIN_NODES)},
}


def resolve_dao_origin_node(value: str) -> str | None:
    return DAO_ORIGIN_NODE_ALIASES.get(value.strip())


__all__ = [
    "DAO_ORIGIN_CODEX",
    "DAO_ORIGIN_CONTENT_VERSION",
    "DAO_ORIGIN_EXPIRY_SECONDS",
    "DAO_ORIGIN_FIRST_REWARD",
    "DAO_ORIGIN_KEY",
    "DAO_ORIGIN_LOCATION",
    "DAO_ORIGIN_NODE_LABELS",
    "DAO_ORIGIN_NODES",
    "DAO_ORIGIN_PERMISSION",
    "DAO_ORIGIN_QUOTA_KEY",
    "DAO_ORIGIN_RULE_VERSION",
    "DAO_ORIGIN_REPEAT_REWARD",
    "DAO_ORIGIN_STAMINA_COST",
    "DAO_ORIGIN_STORY_FLAG",
    "resolve_dao_origin_node",
]
