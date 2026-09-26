"""Adventure domain services and versioned bounty definitions."""

from .models import BountyAcceptRecord, BountyBoardRecord, BountyClaimRecord, BountyOfferView
from .mainline_models import (
    MainlineClaimRecord,
    MainlineStageView,
    MainlineStartRecord,
    MainlineStatusRecord,
)
from .mainline import (
    MAINLINE_CONTENT_VERSION,
    MAINLINE_RULE_VERSION,
    MAINLINE_STAGE_COUNT,
    MAINLINE_STORY_KEY,
    MainlineDefinition,
    mainline_definition,
    mainline_first_clear_key,
    mainline_first_clear_reward,
    mainline_prerequisites_met,
    mainline_prerequisite_met,
    mainline_repeat_reward,
    mainline_stage,
    mainline_stage_definition,
    mainline_stage_status,
    mainline_status,
)
from .rules import bounty_definition, resolve_bounty
from .three_realms import (
    THREE_REALMS_CONTENT_VERSION,
    THREE_REALMS_LANES,
    THREE_REALMS_RULE_VERSION,
    THREE_REALMS_STORY_KEY,
    three_realms_definition,
)

__all__ = [
    "BountyAcceptRecord",
    "BountyBoardRecord",
    "BountyClaimRecord",
    "BountyOfferView",
    "MainlineClaimRecord",
    "MainlineStageView",
    "MainlineStartRecord",
    "MainlineStatusRecord",
    "MAINLINE_CONTENT_VERSION",
    "MAINLINE_RULE_VERSION",
    "MAINLINE_STAGE_COUNT",
    "MAINLINE_STORY_KEY",
    "MainlineDefinition",
    "bounty_definition",
    "mainline_definition",
    "mainline_first_clear_key",
    "mainline_first_clear_reward",
    "mainline_prerequisites_met",
    "mainline_prerequisite_met",
    "mainline_repeat_reward",
    "mainline_stage",
    "mainline_stage_definition",
    "mainline_stage_status",
    "mainline_status",
    "resolve_bounty",
    "THREE_REALMS_CONTENT_VERSION",
    "THREE_REALMS_LANES",
    "THREE_REALMS_RULE_VERSION",
    "THREE_REALMS_STORY_KEY",
    "three_realms_definition",
]
