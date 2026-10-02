"""Rules for the ancestral-hall solo secret realm."""

from __future__ import annotations

ANCESTRAL_HALL_KEY = "instance.secret_realm.ancestral_hall"
ANCESTRAL_HALL_LOCATION = "beast.ancestral_lake"
ANCESTRAL_HALL_NODES = (
    "ancestral_gate",
    "oath_stones",
    "bloodline_corridor",
    "ancestral_spirit",
    "founder_altar",
)
ANCESTRAL_HALL_ENEMY = "enemy.ancestral_spirit"
ANCESTRAL_HALL_STAMINA_COST = 25
ANCESTRAL_HALL_WEEKLY_LIMIT = 1
ANCESTRAL_HALL_EXPIRY_SECONDS = 60 * 60
ANCESTRAL_HALL_STORY_FLAG = "story.ancestral_hall"
ANCESTRAL_HALL_CODEX_ENTRY = "codex.domain.ancestral_hall"

ANCESTRAL_HALL_NODE_LABELS = {
    "ancestral_gate": "祖灵门",
    "oath_stones": "誓言石阵",
    "bloodline_corridor": "血脉回廊",
    "ancestral_spirit": "祖灵守灵",
    "founder_altar": "始祖祭坛",
}

ANCESTRAL_HALL_NODE_ALIASES = {
    **{key: key for key in ANCESTRAL_HALL_NODES},
    "祖灵门": "ancestral_gate",
    "誓言石阵": "oath_stones",
    "血脉回廊": "bloodline_corridor",
    "祖灵守灵": "ancestral_spirit",
    "始祖祭坛": "founder_altar",
}


def resolve_ancestral_hall_node(value: str) -> str | None:
    return ANCESTRAL_HALL_NODE_ALIASES.get(value.strip())


__all__ = [
    "ANCESTRAL_HALL_CODEX_ENTRY",
    "ANCESTRAL_HALL_ENEMY",
    "ANCESTRAL_HALL_EXPIRY_SECONDS",
    "ANCESTRAL_HALL_KEY",
    "ANCESTRAL_HALL_LOCATION",
    "ANCESTRAL_HALL_NODE_LABELS",
    "ANCESTRAL_HALL_NODES",
    "ANCESTRAL_HALL_STAMINA_COST",
    "ANCESTRAL_HALL_STORY_FLAG",
    "ANCESTRAL_HALL_WEEKLY_LIMIT",
    "resolve_ancestral_hall_node",
]
