"""Persistence-facing errors grouped in one stable module.

Application layers may translate these errors into adapter responses without
depending on the SQLite implementation module.
"""

class RepositoryBusyError(RuntimeError):
    """The database did not become available before the retry budget ended."""


class OperationConflictError(RuntimeError):
    """An operation ID was reused with a different actor or input."""


class PlayerNotFoundError(RuntimeError):
    """The requested platform identity has no player record."""


class PlayerSuspendedError(RuntimeError):
    """A suspended or deleted player cannot perform a write operation."""


class DaoNameTakenError(RuntimeError):
    """The requested dao name is already used by another player."""


class RenameCardRequiredError(RuntimeError):
    """A named player needs a rename card before changing dao name again."""


class PlayerStageConflictError(RuntimeError):
    """The player is not in the stage required by an onboarding action."""


class LocationRequiredError(RuntimeError):
    """The player must be at a specific location before an action can run."""


class LocationRequirementError(RuntimeError):
    """The player does not satisfy a destination's realm or quest gate."""


class VoidQuestMissingError(RuntimeError):
    """The player has not earned the void refining permit."""


class VoidLocationRequiredError(RuntimeError):
    """Void refining must be prepared at an approved void location."""


class VoidResourceInsufficientError(RuntimeError):
    """The player lacks a void-specific resource for the operation."""


class VoidInstabilityActiveError(RuntimeError):
    """A failed void operation is still imposing instability."""


class VoidRouteLockedError(RuntimeError):
    """The requested route is not available in the current content."""


class VoidTravelBusyError(RuntimeError):
    """Another movement or void session is active."""


class VoidAnchorInsufficientError(RuntimeError):
    """The player lacks enough anchors for a route."""


class VoidRouteNotFoundError(RuntimeError):
    """The player has no route session to settle."""


class VoidRouteNotReadyError(RuntimeError):
    """The route has not reached its arrival time."""


class CloudRouteLockedError(RuntimeError):
    """The v0.2 cloud route is unavailable for the current player."""


class CloudFareInsufficientError(RuntimeError):
    """The player lacks the cloud-boat fare."""


class CloudBoatBusyError(RuntimeError):
    """The player already has a cloud-boat or other locked action."""


class CloudBoatNotFoundError(RuntimeError):
    """The player has no cloud-boat session to settle."""


class CloudBoatNotReadyError(RuntimeError):
    """The cloud-boat session has not reached its arrival time."""


class AdvancedCavePassMissingError(RuntimeError):
    """The advanced cave pass is not available for the selected route."""


class ArrayHallPermissionDeniedError(RuntimeError):
    """The player cannot use the formation hall."""


class DemonIntroRequirementError(RuntimeError):
    """The demon-realm introduction prerequisites are incomplete."""


class DemonIntroAlreadyCompletedError(RuntimeError):
    """The one-time demon introduction was already completed."""


class ResourceInsufficientError(RuntimeError):
    """A player does not have enough of a spendable resource."""


class EnergyInsufficientError(RuntimeError):
    """A player does not have enough energy for production."""


class MaterialInsufficientError(RuntimeError):
    """A player does not have enough recipe inputs."""


class ToolMissingError(RuntimeError):
    """The recipe's required production tool is not owned."""


class ToolDurabilityInsufficientError(RuntimeError):
    """The recipe's required tool cannot pay its durability cost."""


class RecipeRequirementError(RuntimeError):
    """The player does not satisfy a recipe's profession, realm or location gate."""


class CrossRealmRecipeLockedError(RecipeRequirementError):
    """The cross-realm recipe is not available in the current context."""


class CrossRealmAllianceMissingError(RecipeRequirementError):
    """The player lacks the path or alliance required by a cross-realm recipe."""


class ContractSlotOccupiedError(RuntimeError):
    """The player's active contract slot is already occupied."""


class ProductionBusyError(RuntimeError):
    """The player already has a processing production order."""


class ProductionDailyLimitError(RuntimeError):
    """The recipe reached its business-day cap."""


class ProductionNotFoundError(RuntimeError):
    """The player has no production order to settle."""


class ProductionNotReadyError(RuntimeError):
    """A production order has not reached its completion time."""


class ProductionExpiredError(RuntimeError):
    """A production order missed its normal completion window."""


class FacilitySlotNotFoundError(RuntimeError):
    """The requested cave facility slot is unknown."""


class FacilitySlotOccupiedError(RuntimeError):
    """Another owner already claimed the requested facility slot."""


class FacilitySlotNotClaimedError(RuntimeError):
    """The player or sect has no claimed slot for the requested production."""


class FacilityMaintenanceUnpaidError(RuntimeError):
    """The facility is inactive because its business-day fee was not paid."""


class FacilityOwnerRequirementError(RuntimeError):
    """The actor cannot claim or use a facility for the requested owner scope."""


class PathAlreadySelectedError(RuntimeError):
    """The player already has a first path and cannot select another one."""


class SubprofessionRequiredError(RuntimeError):
    """The support path requires a sub-profession choice."""


class CultivationBusyError(RuntimeError):
    """The player already has a running cultivation session."""


class CultivationRecoveryRequiredError(RuntimeError):
    """An expired session must be recovered before another one can start."""


class CultivationDailyLimitError(RuntimeError):
    """The selected cultivation mode reached its business-day quota."""


class CultivationRequirementError(RuntimeError):
    """The player does not satisfy the selected cultivation mode's gate."""


class CultivationNotFoundError(RuntimeError):
    """The player has no running cultivation session."""


class CultivationNotReadyError(RuntimeError):
    """A cultivation session has not reached its end time."""


class CultivationAlreadyReadyError(RuntimeError):
    """A cultivation session reached its end and must be settled, not cancelled."""


class CultivationExpiredError(RuntimeError):
    """A session missed its normal settlement window and needs recovery."""


class CultivationAlreadyRecoveredError(RuntimeError):
    """An expired session already received its one allowed recovery result."""


class RetreatContentClosedError(RuntimeError):
    """The requested retreat mode is registered but not open."""


class RetreatBusyError(RuntimeError):
    """The player already has a long-running action or retreat."""


class RetreatDailyLimitError(RuntimeError):
    """The player reached the retreat mode's business-day quota."""


class RetreatNotFoundError(RuntimeError):
    """The player has no active retreat to settle."""


class RetreatNotReadyError(RuntimeError):
    """The retreat has not reached its end time."""


class RetreatExpiredError(RuntimeError):
    """The retreat is outside its normal settlement window."""


class RetreatAlreadySettledError(RuntimeError):
    """The active retreat already has a settled result."""


class ResidenceContentClosedError(RuntimeError):
    """The requested residence is registered but not open."""


class ResidenceAlreadyActiveError(RuntimeError):
    """The player already has an active residence."""


class ResidenceNotFoundError(RuntimeError):
    """The player has no active residence."""


class ResidenceRequiredError(RuntimeError):
    """The requested action requires an active residence."""


class ResidencePlotRequiredError(RuntimeError):
    """The active residence does not provide a usable field plot."""


class LocalReputationInsufficientError(RuntimeError):
    """The player has not reached a residence's local reputation gate."""


class CropContentClosedError(RuntimeError):
    """The requested crop is registered but not open."""


class FieldPlotBusyError(RuntimeError):
    """The residence plot already contains a growing crop."""


class FieldPlotNotFoundError(RuntimeError):
    """The player has no current field plot to operate on."""


class FieldPlotNotReadyError(RuntimeError):
    """The crop has not reached its harvest time."""


class FieldPlotWitheredError(RuntimeError):
    """The crop was not harvested within its settlement window."""


class FieldPlotAlreadyHarvestedError(RuntimeError):
    """The current field plot has already been harvested."""


class CropDailyLimitError(RuntimeError):
    """The crop reached its business-day planting quota."""


class CommissionNotFoundError(RuntimeError):
    """The requested town commission is not published for this business day."""


class CommissionStockExhaustedError(RuntimeError):
    """The global stock for a town commission has been claimed."""


class CommissionAlreadyAcceptedError(RuntimeError):
    """The player already accepted this town commission."""


class CommissionQuotaError(RuntimeError):
    """The player has reached the daily town commission acceptance limit."""


class CommissionExpiredError(RuntimeError):
    """The town commission can no longer be delivered."""


class CommissionNotAcceptedError(RuntimeError):
    """The player has no accepted commission to deliver."""


class CommissionMaterialInsufficientError(RuntimeError):
    """The player lacks materials required by a town commission."""


class CommissionAlreadyDeliveredError(RuntimeError):
    """The town commission was already delivered."""


class ServiceRequirementError(RuntimeError):
    """The requested service or provider teaching requirement is unavailable."""


class ServiceReputationInsufficientError(RuntimeError):
    """The provider has not reached the service reputation gate."""


class ServiceLocationConflictError(RuntimeError):
    """The provider and publisher are not at the required location."""


class ServiceSelfAcceptError(RuntimeError):
    """A publisher cannot accept their own service order."""


class ServiceOrderConflictError(RuntimeError):
    """The service order is not in the state required by the operation."""


class ServiceNotFoundError(RuntimeError):
    """The requested service order does not exist for the actor."""


class ServiceDailyLimitError(RuntimeError):
    """The provider reached the service's business-day acceptance cap."""


class ServiceExpiredError(RuntimeError):
    """The service order expired before it could be accepted."""


class ServiceAlreadySettledError(RuntimeError):
    """The service order already has a terminal settlement."""


class RouteContentClosedError(RuntimeError):
    """The requested livelihood route or cargo is not open."""


class RouteCargoRequirementError(RuntimeError):
    """The route cargo is invalid, unavailable or over the route value limit."""


class RouteLocationRequirementError(RuntimeError):
    """The player is not at the route's source location."""


class RouteQuotaError(RuntimeError):
    """The player reached the route's business-day limit."""


class RouteBusyError(RuntimeError):
    """Another movement or player session prevents starting a route."""


class RouteNotFoundError(RuntimeError):
    """The player has no route waiting for settlement."""


class RouteNotReadyError(RuntimeError):
    """The route has not reached its arrival time."""


class RouteAlreadySettledError(RuntimeError):
    """The route already has a terminal settlement."""


class ProjectNotFoundError(RuntimeError):
    """The requested weekly public project does not exist."""


class ProjectContentClosedError(RuntimeError):
    """The requested public project is not open in the current content."""


class ProjectContributionLimitError(RuntimeError):
    """A single public-project contribution exceeds the point cap."""


class ProjectContributionRequirementError(RuntimeError):
    """The selected resource cannot contribute to this public project."""


class ProjectAlreadyCompleteError(RuntimeError):
    """The public project has already reached its contribution requirements."""


class ProjectNotReadyError(RuntimeError):
    """The public project is not ready for reward settlement."""


class SectContentClosedError(RuntimeError):
    """The requested sect content is not open."""


class SectNameInvalidError(RuntimeError):
    """The sect name or motto does not satisfy content limits."""


class SectRequirementError(RuntimeError):
    """The player does not satisfy the sect creation requirement."""


class SectAlreadyJoinedError(RuntimeError):
    """The player already belongs to a sect."""


class SectJoinCooldownError(RuntimeError):
    """The player is still in the post-leave sect cooldown."""


class SectNotFoundError(RuntimeError):
    """The requested sect does not exist or is not active."""


class SectFullError(RuntimeError):
    """The sect has no available member slot."""


class SectApplicationExistsError(RuntimeError):
    """The player already has a pending application for this sect."""


class SectApplicationNotFoundError(RuntimeError):
    """The requested sect application does not exist."""


class SectApplicationExpiredError(RuntimeError):
    """The requested sect application has expired."""


class SectPermissionDeniedError(RuntimeError):
    """The actor does not have the required sect role."""


class SectAssetLockedError(RuntimeError):
    """The player has an active session or order that blocks leaving."""


class SectLeaderCannotLeaveError(RuntimeError):
    """The sect leader must transfer leadership before leaving."""


class PartyNotFoundError(RuntimeError):
    """The requested party does not exist or is not visible to the actor."""


class PartyAlreadyMemberError(RuntimeError):
    """The player already belongs to a forming or active party."""


class PartyInvitationExistsError(RuntimeError):
    """The target already has a pending invitation for a party."""


class PartyInvitationNotFoundError(RuntimeError):
    """The player has no pending invitation for the requested party."""


class PartyInvitationExpiredError(RuntimeError):
    """The party confirmation window has expired."""


class PartyLocationMismatchError(RuntimeError):
    """Party members must share the party's frozen location."""


class PartyPermissionDeniedError(RuntimeError):
    """The actor lacks the required party role."""


class PartyStateConflictError(RuntimeError):
    """The requested party transition is invalid for its current state."""


class PartyNotReadyError(RuntimeError):
    """The party does not have two active, confirmed members."""


class MentorRequirementError(RuntimeError):
    """The actor or target does not satisfy the mentor relationship gate."""


class MentorRelationConflictError(RuntimeError):
    """Either player already has an active or pending mentor relationship."""


class MentorInvitationNotFoundError(RuntimeError):
    """The requested mentor invitation does not exist for the actor."""


class MentorInvitationExpiredError(RuntimeError):
    """The requested mentor invitation has expired."""


class MentorPermissionDeniedError(RuntimeError):
    """The actor lacks permission for the mentor transition."""


class MentorGraduationNotReadyError(RuntimeError):
    """The apprentice has not satisfied all graduation conditions."""


class MentorStateConflictError(RuntimeError):
    """The mentor relation is not in a state that accepts this transition."""


class EndingInvalidError(RuntimeError):
    """The requested terminal ending key is not supported."""


class AscensionRequirementError(RuntimeError):
    """The player is not ready to choose a terminal ending."""


class EndingAlreadyChosenError(RuntimeError):
    """A different terminal ending has already been chosen."""


class ConstitutionAlreadySelectedError(RuntimeError):
    """The player already has a main constitution."""


class ConstitutionSameError(RuntimeError):
    """The requested reshape target is already active."""


class ConstitutionNotFoundError(RuntimeError):
    """The player has not selected a constitution."""


class ConstitutionCooldownError(RuntimeError):
    """The constitution reshape cooldown is still active."""


class ConstitutionBusyError(RuntimeError):
    """A long-running action prevents constitution mutation."""


class TalentNodeAlreadyLearnedError(RuntimeError):
    """The requested talent node is already learned."""


class TalentPathMismatchError(RuntimeError):
    """The requested tree does not match the player's primary path."""


class TalentPrerequisiteError(RuntimeError):
    """The previous talent tier has not been learned."""


class TalentBusyError(RuntimeError):
    """A long-running action prevents talent mutation."""


class SkillAlreadyMaxedError(RuntimeError):
    """The requested skill has reached the current mastery cap."""


class SkillNotAvailableError(RuntimeError):
    """The requested skill is not available to the player's primary path."""


class SkillBusyError(RuntimeError):
    """A long-running action prevents skill mutation."""


class EquipmentNotOwnedError(RuntimeError):
    """The player does not own the requested equipment."""


class EquipmentAmbiguousError(RuntimeError):
    """More than one matching equipment instance needs an explicit selector."""


class EquipmentTemperingMaxedError(RuntimeError):
    """The equipment has reached the current tempering cap."""


class EquipmentBusyError(RuntimeError):
    """A long-running action prevents equipment mutation."""


class RealmCultivationInsufficientError(RuntimeError):
    """The player has not reached the next layer threshold."""


class RealmLayerInvalidError(RuntimeError):
    """The player cannot advance beyond the current realm."""


class BreakthroughBusyError(RuntimeError):
    """The player already has a preparing breakthrough."""


class BreakthroughNotFoundError(RuntimeError):
    """The player has no breakthrough session to settle."""


class BreakthroughNotReadyError(RuntimeError):
    """The breakthrough session has not reached its end time."""


class BreakthroughExpiredError(RuntimeError):
    """The breakthrough session is outside its settlement window."""


class BreakthroughRequirementError(RuntimeError):
    """The player is not eligible for the requested breakthrough."""


class FoundationQualityInsufficientError(RuntimeError):
    """The player's foundation quality is below a breakthrough requirement."""


class WeaknessActiveError(RuntimeError):
    """A temporary breakthrough weakness blocks high-risk actions."""


class WeaknessNotActiveError(RuntimeError):
    """There is no breakthrough weakness to recover."""


class DomainCrackActiveError(RuntimeError):
    """The player cannot use domain-bound progression while cracked."""


class DomainSelectionBusyError(RuntimeError):
    """The player already has a pending domain confirmation."""


class DomainAlreadySelectedError(RuntimeError):
    """The player already selected a domain."""


class DomainNotEligibleError(RuntimeError):
    """The player does not meet domain selection prerequisites."""


class DomainEnergyInsufficientError(RuntimeError):
    """The requested domain activation has insufficient charge."""


class DomainConflictError(RuntimeError):
    """The requested domain conflicts with the current party state."""


class SoulPowerInsufficientError(RuntimeError):
    """The player lacks the soul power required for soul transformation."""


class FactionReputationInsufficientError(RuntimeError):
    """No faction reputation reached the soul transformation threshold."""


class CultivationInsufficientError(RuntimeError):
    """The player lacks the total cultivation for soul transformation."""


class RealmMismatchError(RuntimeError):
    """The source realm or layer does not match the requested breakthrough."""


class CurrencyInsufficientError(RuntimeError):
    """The player does not have enough spirit stones."""


class ProtectionItemInsufficientError(RuntimeError):
    """The requested breakthrough protection item is missing."""


class QuestRequirementError(RuntimeError):
    """A progression quest flag is required before an action can start."""


class HeartDemonPendingError(RuntimeError):
    """The player has an unresolved heart-demon session."""


class HeartDemonAlreadyResolvedError(RuntimeError):
    """A new choice was submitted after the personal event was resolved."""


class SoulFatigueActiveError(RuntimeError):
    """The player's soul fatigue window is still active."""


class PollutionTooHighError(RuntimeError):
    """Cross-realm exploration is blocked by excessive pollution."""


class SoulExhaustionActiveError(RuntimeError):
    """A failed cross-realm action left the player temporarily exhausted."""


class TravelBusyError(RuntimeError):
    """The player has another active movement or long-running action."""


class TravelNotFoundError(RuntimeError):
    """The player has no movement session to settle."""


class TravelNotReadyError(RuntimeError):
    """The movement session has not reached its arrival time."""


class ExplorationBusyError(RuntimeError):
    """The player already has an active exploration or another locked action."""


class ExplorationNotFoundError(RuntimeError):
    """The player has no exploration session to settle or cancel."""


class ExplorationNotReadyError(RuntimeError):
    """The exploration session has not reached its end time."""


class ExplorationExpiredError(RuntimeError):
    """The exploration session exceeded its normal settlement window."""


class ExplorationCombatPendingError(RuntimeError):
    """The exploration rolled a combat encounter that is still locked."""


class ExplorationStormNotPendingError(RuntimeError):
    """The exploration has no cloud-boat storm choice waiting."""


class ExplorationStormChoiceError(RuntimeError):
    """The requested cloud-boat storm choice is not supported."""


class PartyBattleNotFoundError(RuntimeError):
    """The requested party battle does not exist or is not visible to the actor."""


class PartyBattleBusyError(RuntimeError):
    """The party or one of its members already has a locked party battle."""


class PartyBattlePermissionError(RuntimeError):
    """The actor cannot start or settle the party battle."""


class PartyBattleRequirementError(RuntimeError):
    """The party is not ready for its location or enemy encounter."""


class BoundaryRealmRequirementError(PartyBattleRequirementError):
    """A boundary-realm member is missing the cross-realm qualification."""


class CrossRealmPartyRequirementError(PartyBattleRequirementError):
    """A v0.3 cross-realm dungeon party requirement is not satisfied."""


class BoundaryRealmResourceError(PartyBattleRequirementError):
    """A boundary-realm party lacks stamina or its team ticket."""


class PartyBattleNotReadyError(RuntimeError):
    """The party battle has not reached a terminal result."""


class FinalBattleNotFoundError(RuntimeError):
    """The final battle does not exist or is not visible to the actor."""


class FinalBattleRequirementError(RuntimeError):
    """The initiator or helper does not meet the final battle requirements."""


class FinalBattleBusyError(RuntimeError):
    """The player already has an active action or final battle lock."""


class FinalBattlePermissionError(RuntimeError):
    """The actor cannot perform this final battle operation."""


class FinalBattleNotReadyError(RuntimeError):
    """The final battle is not ready for the requested transition."""


class FinalBattleCooldownError(RuntimeError):
    """The initiator is still in the final battle retry cooldown."""


class FinalBattleMemberLimitError(RuntimeError):
    """The final battle already has its maximum number of participants."""


class ExplorationQuotaExhaustedError(RuntimeError):
    """The mode reached its business-day quota."""


class BountyDailyLimitError(RuntimeError):
    """The player already accepted a bounty for this business day."""


class BountyNotFoundError(RuntimeError):
    """The player has no current bounty to claim."""


class BountyContentClosedError(RuntimeError):
    """The bounty depends on a runtime that is still closed."""


class BountyRequirementError(RuntimeError):
    """The player does not satisfy a bounty's realm or stage gate."""


class BountyIncompleteError(RuntimeError):
    """The accepted bounty target has not been completed."""


class BountyExpiredError(RuntimeError):
    """The accepted bounty passed its deadline without a claim."""


class BountyAlreadyClaimedError(RuntimeError):
    """The current bounty reward has already been claimed."""


class MainlineContentClosedError(RuntimeError):
    """The requested mainline stage is documented but not open yet."""


class MainlineRequirementError(RuntimeError):
    """The player does not satisfy a mainline stage prerequisite."""


class MainlineNotStartedError(RuntimeError):
    """The requested mainline stage has no running attempt."""


class MainlineAlreadyRunningError(RuntimeError):
    """The requested mainline stage already has a running attempt."""


class CheckinAlreadyClaimedError(RuntimeError):
    """The player already completed today's daily check-in."""


class RoutineMakeupDateError(RuntimeError):
    """The requested makeup date is outside the allowed window."""


class RoutineMakeupNotEligibleError(RuntimeError):
    """The requested date was already claimed or is otherwise ineligible."""


class RoutineMakeupLimitError(RuntimeError):
    """The player reached the monthly makeup limit."""


class SpiritTreeWateredError(RuntimeError):
    """The spirit tree was already watered for this business day."""


class SpiritTreeCooldownError(RuntimeError):
    """The spirit tree is in its post-harvest cooldown."""


class SpiritTreeNotReadyError(RuntimeError):
    """The spirit tree has not reached seven waterings."""


class SevenDayNotStartedError(RuntimeError):
    """The player has not started the seven-day onboarding campaign."""


class SevenDayGoalInvalidError(RuntimeError):
    """The requested seven-day goal number is invalid."""


class SevenDayGoalNotOpenError(RuntimeError):
    """The requested seven-day goal is still in a future business day."""


class SevenDayGoalNotCompletedError(RuntimeError):
    """The requested seven-day goal has no qualifying activity yet."""


class SevenDayGoalAlreadyClaimedError(RuntimeError):
    """The requested seven-day goal reward was already claimed."""


class EventNotActiveError(RuntimeError):
    """No open or claimable world-event round is available."""


class EventContributionInsufficientError(RuntimeError):
    """The player has not reached the event reward contribution threshold."""


class EventRewardAlreadyClaimedError(RuntimeError):
    """The player already claimed this event round's reward."""


class EventRewardExpiredError(RuntimeError):
    """The event reward window has closed."""


class EventSourceNotEligibleError(RuntimeError):
    """No server-settled operation can be projected into the event."""


class ArenaSnapshotRequirementError(RuntimeError):
    """The player cannot publish an arena snapshot in the current state."""


class ArenaPlayerBusyError(RuntimeError):
    """The player has another asset-locking session in progress."""


class ArenaSnapshotNotFoundError(RuntimeError):
    """The requested arena snapshot does not exist or is not owned by the player."""


class ArenaSnapshotExpiredError(RuntimeError):
    """The selected arena snapshot is no longer matchable."""


class ArenaOpponentUnavailableError(RuntimeError):
    """No compatible published arena snapshot is available."""


class ArenaChallengeCapError(RuntimeError):
    """The player's daily arena challenge cap has been reached."""


class ArenaMatchRequirementError(RuntimeError):
    """The requested arena challenge does not satisfy mode requirements."""


class ArenaMatchNotFoundError(RuntimeError):
    """The requested arena match does not exist or is not visible to the player."""


class ArenaRewardAlreadyClaimedError(RuntimeError):
    """The arena match result has already been acknowledged."""


class ArenaRewardNotAvailableError(RuntimeError):
    """The player has no pending arena result to acknowledge."""


class TeamArenaSnapshotRequirementError(RuntimeError):
    """The party cannot publish a usable team arena snapshot."""


class TeamArenaSnapshotNotFoundError(RuntimeError):
    """The requested team arena snapshot does not exist."""


class TeamArenaOpponentUnavailableError(RuntimeError):
    """No compatible team snapshot is currently matchable."""


class TeamArenaPermissionError(RuntimeError):
    """The actor is not allowed to operate the team arena party."""


class TeamArenaBusyError(RuntimeError):
    """The team is already committed to another battle."""


class TeamArenaChallengeCapError(RuntimeError):
    """The team arena daily challenge cap has been reached."""


class FinalHeavenRankingNotFinalizedError(RuntimeError):
    """The requested season has not reached its frozen ranking state."""


class FinalHeavenRewardNotEligibleError(RuntimeError):
    """The player has no claimable final-heaven ranking reward."""


class FinalHeavenRewardAlreadyClaimedError(RuntimeError):
    """The player already claimed this season's ranking rewards."""


class FinalHeavenClaimExpiredError(RuntimeError):
    """The final-heaven ranking reward window has closed."""


class AchievementInvalidError(RuntimeError):
    """The requested achievement is not registered."""


class AchievementNotCompletedError(RuntimeError):
    """The requested achievement has no qualifying source event yet."""


class AchievementAlreadyClaimedError(RuntimeError):
    """The requested achievement reward was already claimed."""


class HonorTitleNotFoundError(RuntimeError):
    """The requested title is not owned by the player."""


class HonorTitleClosedError(RuntimeError):
    """The requested title or achievement is not open in the current content."""


class RedemptionCodeInvalidError(RuntimeError):
    """The submitted code is not configured."""


class RedemptionCodeExpiredError(RuntimeError):
    """The configured code is outside its validity window."""


class RedemptionCodeRevokedError(RuntimeError):
    """The configured code was revoked before redemption."""


class RedemptionCodeExhaustedError(RuntimeError):
    """The configured code has no remaining claims."""


class RedemptionCodeAlreadyClaimedError(RuntimeError):
    """The player already redeemed this code."""


class FatePoolInvalidError(RuntimeError):
    """The requested fate pool or draw count is not registered."""


class FatePoolNotOpenError(RuntimeError):
    """The requested fate pool is not available in the current content."""


class FateDrawInsufficientError(RuntimeError):
    """The player lacks the ticket or spirit stones required for a draw."""


class BillingReceiptInvalidError(RuntimeError):
    """The external billing receipt failed signature or contract validation."""


class BillingReceiptAlreadyUsedError(RuntimeError):
    """A signed receipt was already consumed by another operation."""


class DaoContractInvalidError(RuntimeError):
    """The requested contract is not registered."""


class DaoContractAlreadyClaimedError(RuntimeError):
    """The daily entitlement was already claimed for the business date."""


class DaoContractNotActiveError(RuntimeError):
    """The contract is not active for the requested business date."""


class DaoContractAlreadyRevokedError(RuntimeError):
    """The contract is already revoked or cannot be revoked."""


class WayfaringNotStartedError(RuntimeError):
    """The player has not started the current wayfaring pass."""


class WayfaringAlreadyStartedError(RuntimeError):
    """The current wayfaring cycle is already active."""


class WayfaringLevelInvalidError(RuntimeError):
    """The requested wayfaring level is outside the configured range."""


class WayfaringLevelLockedError(RuntimeError):
    """The player has not earned enough points for the requested level."""


class WayfaringClaimAlreadyExistsError(RuntimeError):
    """The requested wayfaring track was already claimed."""


class WayfaringPaidTrackInactiveError(RuntimeError):
    """The monthly dao contract is not active for the paid track."""


class DaoUnionRequirementError(RuntimeError):
    """The player does not satisfy the 合道 entry contract."""


class TribulationEntryRequirementError(RuntimeError):
    """The player does not satisfy the 渡劫 entry contract."""


class TrialSequenceError(RuntimeError):
    """The requested tribulation trial is unavailable or out of order."""


class TribulationTrialBusyError(RuntimeError):
    """Another tribulation trial is already preparing."""


class TribulationTrialNotFoundError(RuntimeError):
    """There is no preparing tribulation trial to settle."""


class TribulationTrialNotReadyError(RuntimeError):
    """The preparing tribulation trial has not reached its end time."""


class TribulationCooldownError(RuntimeError):
    """The requested trial is still in its failure cooldown."""


class TribulationDebtBlockedError(RuntimeError):
    """Tribulation debt is too high to start another trial."""


class TribulationTokenInsufficientError(RuntimeError):
    """The player lacks the token required by a tribulation trial."""


class ThreeRealmReputationInsufficientError(RuntimeError):
    """The player lacks the three realm reputation needed by trial two."""


class DaoFruitChoiceError(RuntimeError):
    """The chosen dao fruit is invalid or already locked."""


class WalletNotFoundError(RuntimeError):
    """The requested player wallet does not exist."""


class BalanceInsufficientError(RuntimeError):
    """The wallet cannot pay the requested amount."""


class CurrencyInvalidError(RuntimeError):
    """The operation requested an unsupported currency."""


class MarketOrderNotFoundError(RuntimeError):
    """The requested market order does not exist."""


class MarketOrderExpiredError(RuntimeError):
    """The market order has passed its expiry deadline."""


class MarketOrderAlreadySettledError(RuntimeError):
    """The market order is already in a terminal state."""


class MarketPriceInvalidError(RuntimeError):
    """The market quantity or unit price violates the v0.1 limits."""


class MarketItemLockedError(RuntimeError):
    """The seller lacks enough unlocked inventory for the order."""


class MarketOrderNotListedError(RuntimeError):
    """The order is not available for purchase or cancellation."""


class MarketBuyerCapacityInsufficientError(RuntimeError):
    """The buyer cannot fit the purchased stack in their inventory."""


class PurchaseOrderCapError(RuntimeError):
    """The buyer has reached the simultaneous purchase-order limit."""


class PurchaseItemForbiddenError(RuntimeError):
    """The requested purchase item is not an explicit tradeable item."""


class PurchaseEscrowInsufficientError(RuntimeError):
    """The buyer cannot reserve the purchase amount and fee."""


class PurchaseOrderNotFoundError(RuntimeError):
    """The requested purchase order does not exist."""


class PurchaseOrderStateConflictError(RuntimeError):
    """The purchase order is not in a state valid for the requested action."""


class PurchaseSelfMatchError(RuntimeError):
    """A buyer cannot match their own purchase order."""


class PurchaseItemLockedError(RuntimeError):
    """The seller does not have enough unlocked inventory to match the order."""


class PurchaseOrderExpiredError(RuntimeError):
    """The purchase order has expired."""


class PurchaseDeliveryExpiredError(RuntimeError):
    """The seller missed the ten-minute delivery window."""


class PurchaseBuyerCapacityInsufficientError(RuntimeError):
    """The buyer cannot fit the delivered purchase in their inventory."""


class PurchasePermissionDeniedError(RuntimeError):
    """The buyer lacks the reputation required to create a cross-realm order."""


class MarketSelfTradeError(RuntimeError):
    """A seller cannot purchase their own order."""


class MarketOrderLimitError(RuntimeError):
    """The seller has reached the simultaneous listing limit."""


class AuctionSlotFullError(RuntimeError):
    """The weekly auction has no free slots."""


class AuctionNotFoundError(RuntimeError):
    """The requested auction does not exist."""


class AuctionBidTooLowError(RuntimeError):
    """The bid does not meet the minimum increment."""


class AuctionSelfBidError(RuntimeError):
    """The seller cannot bid on their own auction."""


class AuctionStateConflictError(RuntimeError):
    """The auction is not in a state valid for the requested action."""


class AuctionSettlementExpiredError(RuntimeError):
    """The auction settlement recovery window has expired."""


class AuctionItemLockedError(RuntimeError):
    """The auction item lock is missing or unavailable."""


class MarketItemForbiddenError(RuntimeError):
    """The requested item is bound, a credential, or otherwise non-tradeable."""


class CrossRealmTradePermissionDeniedError(RuntimeError):
    """The player is not at the required cross-realm trade location."""


class TradeWeeklyCapError(RuntimeError):
    """The player has reached the fixed trade's weekly limit."""


class CrossRealmTradeInputInsufficientError(RuntimeError):
    """The player lacks one of the fixed trade inputs."""


class CrossRealmTradeCurrencyInsufficientError(RuntimeError):
    """The player lacks the fixed trade's spirit-stone cost."""


class ItemBindingActiveError(RuntimeError):
    """The requested inventory quantity is still character-bound."""


class CommissionRecipeForbiddenError(RuntimeError):
    """The recipe is not available for player production commissions."""


class CommissionEscrowConflictError(RuntimeError):
    """The commission cannot reserve or release its reward escrow."""


class CommissionStateConflictError(RuntimeError):
    """The commission is not in a state valid for the requested transition."""


class CommissionNotFoundError(RuntimeError):
    """The requested production commission does not exist."""


class CommissionExpiredError(RuntimeError):
    """The production commission passed its deadline."""


class CommissionSelfAcceptError(RuntimeError):
    """A publisher cannot accept their own production commission."""


class CommissionRequirementError(RuntimeError):
    """The producer does not satisfy recipe or resource requirements."""


class CommissionDeliveryError(RuntimeError):
    """The requested commission delivery transition is invalid."""


class BattleNotFoundError(RuntimeError):
    """The requested battle session does not exist for this player."""


class BattleBusyError(RuntimeError):
    """A player already has a battle or another locked long action."""


class BattleRequirementError(RuntimeError):
    """The player misses a battle location, realm, or state prerequisite."""


class BattleCooldownError(RuntimeError):
    """A recent battle defeat is still imposing its cooldown."""


class BattleNotReadyError(RuntimeError):
    """The server has not yet reached a terminal battle outcome."""


class BattleAlreadySettledError(RuntimeError):
    """The terminal battle was already converted into a settlement."""


class BattleRewardNotAvailableError(RuntimeError):
    """There is no settled victory reward pending for the player."""


class BattleRewardAlreadyClaimedError(RuntimeError):
    """The battle reward was already claimed by a different operation."""


class QuestRequirementError(RuntimeError):
    """The player does not satisfy a quest action or completion gate."""


class QuestAlreadyCompletedError(RuntimeError):
    """The requested one-time quest component has already been completed."""


class QuestNotCompletedError(RuntimeError):
    """The player has not completed all required quest components."""


class QuestResourceInsufficientError(RuntimeError):
    """The player lacks a material required by a quest action."""


class QuestOperationNotFoundError(RuntimeError):
    """A quest source operation cannot be found or is not eligible."""


class DaoUnionQuestRequirementError(RuntimeError):
    """The player has not completed the three dao-union qualification components."""


class DaoOriginTaskRequirementError(RuntimeError):
    """The player is not eligible for a dao-origin task."""


class EndgameRecipeRequirementError(RuntimeError):
    """The player is missing the context required by an endgame recipe."""


class EndgameRecipeAlreadyCreatedError(RuntimeError):
    """A one-time endgame recipe has already been created."""


class EndgameRecipeBusyError(RuntimeError):
    """Another endgame recipe order is still processing."""


class EndgameRecipeNotFoundError(RuntimeError):
    """The player has no endgame recipe order to settle."""


class EndgameRecipeNotReadyError(RuntimeError):
    """The endgame recipe order has not reached its settlement time."""


class ItemNotUsableError(RuntimeError):
    """The requested item has no active player-facing use effect."""


class ItemInsufficientError(RuntimeError):
    """The player does not own enough copies of the requested item."""


class ItemLocationRequiredError(RuntimeError):
    """The item effect requires a different binding location."""


class ItemEffectAlreadyActiveError(RuntimeError):
    """An item effect of the same non-stacking kind is already active."""


class ItemEffectAlreadyPendingError(RuntimeError):
    """A one-shot consumable effect is already waiting to be applied."""
