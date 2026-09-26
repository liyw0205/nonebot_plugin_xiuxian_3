"""Pure rules for the v0.1 mentor relationship slice."""

from __future__ import annotations


MENTOR_CONTENT_VERSION = "content-0.1"
MENTOR_RULE_VERSION = "social-0.1.0"
MENTOR_INVITATION_TTL_SECONDS = 24 * 60 * 60
MENTOR_MAX_APPRENTICES = 3
MENTOR_MASTER_REALM = "foundation"
MENTOR_MASTER_MIN_LAYER = 4
MENTOR_APPRENTICE_REALMS = frozenset({"mortal", "qi_sensing", "qi_gathering"})
MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER = 6
MENTOR_GRADUATION_REALM = "qi_gathering"
MENTOR_GRADUATION_MIN_LAYER = 3
MENTOR_APPRENTICE_LOCAL_REPUTATION = 10
MENTOR_CONTRIBUTION = 20
MENTOR_SERVICE_REPUTATION = 2
_MASTER_REALM_RANKS = {
    "foundation": 3,
    "golden_core": 4,
    "nascent_soul": 5,
    "soul_transformation": 6,
    "void_refining": 7,
    "dao_union": 8,
    "tribulation": 9,
}


def is_master_eligible(realm_key: str, realm_layer: int) -> bool:
    rank = _MASTER_REALM_RANKS.get(realm_key, -1)
    layer = int(realm_layer)
    if rank < _MASTER_REALM_RANKS[MENTOR_MASTER_REALM] or layer < 1:
        return False
    return rank > _MASTER_REALM_RANKS[MENTOR_MASTER_REALM] or layer >= MENTOR_MASTER_MIN_LAYER


def is_apprentice_eligible(stage: str, realm_key: str, realm_layer: int) -> bool:
    if stage not in {"mortal", "seeker", "cultivator"}:
        return False
    if realm_key == "mortal":
        return True
    if realm_key == "qi_sensing":
        return 1 <= int(realm_layer) <= 10
    return realm_key == "qi_gathering" and 1 <= int(realm_layer) <= MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER


def is_graduation_ready(stage: str, realm_key: str, realm_layer: int) -> bool:
    return (
        stage == "cultivator"
        and realm_key == MENTOR_GRADUATION_REALM
        and int(realm_layer) >= MENTOR_GRADUATION_MIN_LAYER
    )


__all__ = [
    "MENTOR_APPRENTICE_LOCAL_REPUTATION",
    "MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER",
    "MENTOR_APPRENTICE_REALMS",
    "MENTOR_CONTENT_VERSION",
    "MENTOR_CONTRIBUTION",
    "MENTOR_GRADUATION_MIN_LAYER",
    "MENTOR_GRADUATION_REALM",
    "MENTOR_INVITATION_TTL_SECONDS",
    "MENTOR_MASTER_MIN_LAYER",
    "MENTOR_MASTER_REALM",
    "MENTOR_MAX_APPRENTICES",
    "MENTOR_RULE_VERSION",
    "MENTOR_SERVICE_REPUTATION",
    "is_apprentice_eligible",
    "is_graduation_ready",
    "is_master_eligible",
]
