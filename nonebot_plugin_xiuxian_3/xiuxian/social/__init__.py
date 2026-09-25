"""Social domain services."""

from .sect_models import SectApplicationRecord, SectRecord
from .party_models import PartyInvitationRecord, PartyMemberRecord, PartyRecord
from .mentor_models import MentorRelationRecord
from .sect_war_models import SectWarClaimRecord, SectWarRecord, SectWarStanding
from .sect_war_federation_models import SectWarFederationResultRecord, SectWarFederationSnapshotRecord
from .sect_war_rules import (
    SECT_WAR_CLAIM_HOURS,
    SECT_WAR_CONTENT_VERSION,
    SECT_WAR_DURATION_MINUTES,
    SECT_WAR_MEMBER_REWARD,
    SECT_WAR_MEMBER_THRESHOLD,
    SECT_WAR_MAX_PARTICIPANTS,
    SECT_WAR_MIN_LEVEL,
    SECT_WAR_REGISTRATION_FEE,
    SECT_WAR_RULE_VERSION,
    SECT_WAR_SECT_REWARD,
)
from .sect_rules import (
    SECT_CREATE_COST,
    SECT_MAX_MEMBERS,
    SECT_APPLICATION_TTL_SECONDS,
    SectRole,
)
from .party_rules import PARTY_CONFIRMATION_TTL_SECONDS, PARTY_MAX_MEMBERS, PARTY_TYPE_EXPLORATION_PAIR, PARTY_TYPE_STANDARD_PVE
from .mentor_rules import (
    MENTOR_APPRENTICE_LOCAL_REPUTATION,
    MENTOR_CONTENT_VERSION,
    MENTOR_CONTRIBUTION,
    MENTOR_INVITATION_TTL_SECONDS,
    MENTOR_MASTER_MIN_LAYER,
    MENTOR_MAX_APPRENTICES,
    MENTOR_RULE_VERSION,
    MENTOR_SERVICE_REPUTATION,
)

__all__ = [
    "SECT_APPLICATION_TTL_SECONDS",
    "SECT_CREATE_COST",
    "SECT_MAX_MEMBERS",
    "SectApplicationRecord",
    "SectRecord",
    "SectRole",
    "PARTY_CONFIRMATION_TTL_SECONDS",
    "PARTY_MAX_MEMBERS",
    "PARTY_TYPE_EXPLORATION_PAIR",
    "PARTY_TYPE_STANDARD_PVE",
    "PartyInvitationRecord",
    "PartyMemberRecord",
    "PartyRecord",
    "MentorRelationRecord",
    "SectWarClaimRecord",
    "SectWarRecord",
    "SectWarStanding",
    "SectWarFederationResultRecord",
    "SectWarFederationSnapshotRecord",
    "SECT_WAR_CLAIM_HOURS",
    "SECT_WAR_CONTENT_VERSION",
    "SECT_WAR_DURATION_MINUTES",
    "SECT_WAR_MEMBER_REWARD",
    "SECT_WAR_MEMBER_THRESHOLD",
    "SECT_WAR_MAX_PARTICIPANTS",
    "SECT_WAR_MIN_LEVEL",
    "SECT_WAR_REGISTRATION_FEE",
    "SECT_WAR_RULE_VERSION",
    "SECT_WAR_SECT_REWARD",
    "MENTOR_APPRENTICE_LOCAL_REPUTATION",
    "MENTOR_CONTENT_VERSION",
    "MENTOR_CONTRIBUTION",
    "MENTOR_INVITATION_TTL_SECONDS",
    "MENTOR_MASTER_MIN_LAYER",
    "MENTOR_MAX_APPRENTICES",
    "MENTOR_RULE_VERSION",
    "MENTOR_SERVICE_REPUTATION",
]
