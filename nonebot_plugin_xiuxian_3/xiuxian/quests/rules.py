"""Stable keys and thresholds for v0.4/v0.5 breakthrough permits."""

from __future__ import annotations

CONTENT_VERSION = "content-0.5"
RULE_VERSION = "quests-0.5.0"

SOUL_QUEST = "quest.soul_transformation"
DOMAIN_COMMISSION = "quest.domain_material_commission"
ANCIENT_DOMAIN_LINE = "quest.ancient_domain_line"
CROSS_REALM_VICTORY = "event.cross_realm_victory"

VOID_QUEST = "quest.break_void"
VOID_WALL_TRIAL = "void_wall_trial"
VOID_ARCHIVE_DELIVERY = "void_archive_delivery"

DOMAIN_COMMISSION_TARGET = 3
ANCIENT_DOMAIN_TARGET = 3
VOID_TRIAL_TARGET = 3

DAO_UNION_QUEST = "quest.dao_union"
DAO_UNION_CONTENT_VERSION = "content-0.6"
DAO_UNION_RULE_VERSION = "quests-0.6.0"
DAO_UNION_MAINLINE = "three_realm_mainline"
DAO_UNION_CHALLENGE = "cross_server_challenge"
DAO_UNION_WORK = "endgame_work"
DAO_ORIGIN_CONTENT_VERSION = "content-0.6"
DAO_ORIGIN_RULE_VERSION = "events-0.6.0"
DAO_ORIGIN_GUARD = "task.dao_origin.guard"
DAO_ORIGIN_BUILD = "task.dao_origin.build"
DAO_ORIGIN_TEACH = "task.dao_origin.teach"
DAO_ORIGIN_TASKS = (DAO_ORIGIN_GUARD, DAO_ORIGIN_BUILD, DAO_ORIGIN_TEACH)
DAO_ORIGIN_TARGET = 3
# These values close the documented 1,000/1,000 endgame resource path.
DAO_ORIGIN_REWARDS = {
    DAO_ORIGIN_GUARD: {"dao_fruit_progress": 150, "ascension_merit": 150},
    DAO_ORIGIN_BUILD: {"dao_fruit_progress": 160, "ascension_merit": 150},
    DAO_ORIGIN_TEACH: {"dao_fruit_progress": 160, "ascension_merit": 150},
}
DAO_ORIGIN_WORLD_MERIT = {
    DAO_ORIGIN_GUARD: 300,
    DAO_ORIGIN_BUILD: 300,
    DAO_ORIGIN_TEACH: 400,
}


def realm_rank(realm_key: str) -> int:
    return {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str, required_layer: int = 1) -> bool:
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


__all__ = [
    "ANCIENT_DOMAIN_LINE",
    "ANCIENT_DOMAIN_TARGET",
    "CONTENT_VERSION",
    "CROSS_REALM_VICTORY",
    "DOMAIN_COMMISSION",
    "DOMAIN_COMMISSION_TARGET",
    "RULE_VERSION",
    "SOUL_QUEST",
    "VOID_ARCHIVE_DELIVERY",
    "VOID_QUEST",
    "VOID_TRIAL_TARGET",
    "VOID_WALL_TRIAL",
    "DAO_ORIGIN_BUILD",
    "DAO_ORIGIN_CONTENT_VERSION",
    "DAO_ORIGIN_GUARD",
    "DAO_ORIGIN_REWARDS",
    "DAO_ORIGIN_RULE_VERSION",
    "DAO_ORIGIN_TARGET",
    "DAO_ORIGIN_TASKS",
    "DAO_ORIGIN_TEACH",
    "DAO_ORIGIN_WORLD_MERIT",
    "DAO_UNION_CHALLENGE",
    "DAO_UNION_CONTENT_VERSION",
    "DAO_UNION_MAINLINE",
    "DAO_UNION_QUEST",
    "DAO_UNION_RULE_VERSION",
    "DAO_UNION_WORK",
    "meets_realm",
]
