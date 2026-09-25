"""World events and task projections."""

from .models import SpiritSpringEventRecord
from .demon_models import DemonInvasionEventRecord
from .demon_repository import DemonInvasionRepositoryMixin
from .cross_realm_models import CrossRealmEventRecord
from .cross_realm_repository import CrossRealmEventRepositoryMixin
from .repository import EventsRepositoryMixin
from .heart_demon_models import HeartDemonEventRecord
from .heart_demon_repository import HEART_DEMON_EVENT_KEY, HeartDemonEventRepositoryMixin
from .season_models import FinalHeavenClaimRecord, FinalHeavenSeasonRecord, FinalHeavenStanding
from .season_repository import FinalHeavenSeasonRepositoryMixin
from .season_use_cases import FinalHeavenSeasonApplication
from .three_realms_models import ThreeRealmsClaimRecord, ThreeRealmsSeasonRecord, ThreeRealmsStanding
from .three_realms_repository import ThreeRealmsSeasonRepositoryMixin
from .three_realms_use_cases import ThreeRealmsSeasonApplication
from .three_realms_rules import BOARDS as THREE_REALMS_BOARDS
from .domain_front_models import (
    DomainFrontClaimRecord,
    DomainCoreRedeemRecord,
    DomainFrontRecord,
    DomainFrontSeasonClaimRecord,
    DomainFrontSeasonRecord,
    DomainFrontSeasonStanding,
)
from .domain_front_repository import DomainFrontRepositoryMixin
from .domain_front_use_cases import DomainFrontApplication
from .domain_front_rules import EVENT_KEY as DOMAIN_FRONT_EVENT_KEY
from .void_frontier_models import VoidFrontierClaimRecord, VoidFrontierSeasonRecord, VoidFrontierStanding, VoidFrontierWeeklyRecord
from .void_frontier_repository import VoidFrontierRepositoryMixin
from .void_frontier_use_cases import VoidFrontierApplication
from .rules import (
    EVENT_KEY,
    EVENT_LOCATION,
    EVENT_RULE_VERSION,
    EVENT_TARGET,
    PERSONAL_CONTRIBUTION_CAP,
    PERSONAL_REWARD_THRESHOLD,
)
from .use_cases import EventsApplication

__all__ = [
    "EVENT_KEY",
    "EVENT_LOCATION",
    "EVENT_RULE_VERSION",
    "EVENT_TARGET",
    "EventsApplication",
    "EventsRepositoryMixin",
    "HEART_DEMON_EVENT_KEY",
    "HeartDemonEventRecord",
    "HeartDemonEventRepositoryMixin",
    "DemonInvasionEventRecord",
    "DemonInvasionRepositoryMixin",
    "CrossRealmEventRecord",
    "CrossRealmEventRepositoryMixin",
    "FinalHeavenClaimRecord",
    "FinalHeavenSeasonApplication",
    "FinalHeavenSeasonRecord",
    "FinalHeavenSeasonRepositoryMixin",
    "FinalHeavenStanding",
    "THREE_REALMS_BOARDS",
    "ThreeRealmsClaimRecord",
    "ThreeRealmsSeasonApplication",
    "ThreeRealmsSeasonRecord",
    "ThreeRealmsSeasonRepositoryMixin",
    "ThreeRealmsStanding",
    "PERSONAL_CONTRIBUTION_CAP",
    "PERSONAL_REWARD_THRESHOLD",
    "SpiritSpringEventRecord",
    "DOMAIN_FRONT_EVENT_KEY",
    "DomainFrontApplication",
    "DomainFrontClaimRecord",
    "DomainCoreRedeemRecord",
    "DomainFrontRecord",
    "DomainFrontRepositoryMixin",
    "DomainFrontSeasonClaimRecord",
    "DomainFrontSeasonRecord",
    "DomainFrontSeasonStanding",
    "VoidFrontierApplication",
    "VoidFrontierClaimRecord",
    "VoidFrontierRepositoryMixin",
    "VoidFrontierSeasonRecord",
    "VoidFrontierStanding",
    "VoidFrontierWeeklyRecord",
]
