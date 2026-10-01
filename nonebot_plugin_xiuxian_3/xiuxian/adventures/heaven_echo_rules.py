"""Rules for the heaven-echo solo secret realm."""

from __future__ import annotations


HEAVEN_ECHO_KEY = "instance.secret_realm.heaven_echo"
HEAVEN_ECHO_NODES = (
    "heaven_threshold",
    "echo_corridor",
    "side_story_gate",
)
HEAVEN_ECHO_NODE_LABELS = {
    "heaven_threshold": "天劫门槛",
    "echo_corridor": "回音长廊",
    "side_story_gate": "旁线之门",
}
HEAVEN_ECHO_NODE_ALIASES = {
    **{key: key for key in HEAVEN_ECHO_NODES},
    "天劫门槛": "heaven_threshold",
    "回音长廊": "echo_corridor",
    "旁线之门": "side_story_gate",
    **{str(index + 1): key for index, key in enumerate(HEAVEN_ECHO_NODES)},
}
HEAVEN_ECHO_EXPIRY_SECONDS = 60 * 60
HEAVEN_ECHO_STORY_FLAG = "story.heaven_echo"


def resolve_heaven_echo_node(value: str) -> str | None:
    return HEAVEN_ECHO_NODE_ALIASES.get(value.strip())


__all__ = [
    "HEAVEN_ECHO_EXPIRY_SECONDS",
    "HEAVEN_ECHO_KEY",
    "HEAVEN_ECHO_NODE_LABELS",
    "HEAVEN_ECHO_NODES",
    "HEAVEN_ECHO_STORY_FLAG",
    "resolve_heaven_echo_node",
]
