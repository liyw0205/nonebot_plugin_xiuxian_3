"""Rules for the heaven-echo solo secret realm (content-backed)."""

from __future__ import annotations

from .secret_realm_content import node_aliases, node_labels, secret_realm_record

HEAVEN_ECHO_KEY = "instance.secret_realm.heaven_echo"

_RECORD = secret_realm_record(HEAVEN_ECHO_KEY)

HEAVEN_ECHO_NODES = tuple(str(node["key"]) for node in _RECORD["nodes"])
HEAVEN_ECHO_NODE_LABELS = node_labels(_RECORD)
HEAVEN_ECHO_NODE_ALIASES = node_aliases(_RECORD)
HEAVEN_ECHO_EXPIRY_SECONDS = int(_RECORD["expiry_seconds"])
HEAVEN_ECHO_STORY_FLAG = str(_RECORD["story_flag"])


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
