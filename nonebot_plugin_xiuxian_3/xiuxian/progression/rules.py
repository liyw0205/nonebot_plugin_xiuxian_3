"""Pure rules for the first cultivation loop."""

from __future__ import annotations

from collections.abc import Mapping


REALM_QI_SENSING = "qi_sensing"
MODE_BREATHING = "cultivate.breathing"
RULE_VERSION = "progression-0.1.1"

# Index zero represents the L1 entry point. Values are the minimum realm
# cultivation required for each layer in the content-0.1 snapshot.
QI_SENSING_THRESHOLDS = (0, 80, 170, 280, 410, 560, 730, 920, 1130, 1360)
BREATHING_STAMINA_COST = 2
BREATHING_DURATION_SECONDS = 10 * 60
BREATHING_BASE_CULTIVATION = 40
RECOVERY_PERIOD_SECONDS = 30 * 60


def next_layer_threshold(realm_key: str, layer: int) -> int | None:
    if realm_key != REALM_QI_SENSING or layer < 1:
        return None
    next_layer = layer + 1
    if next_layer > 10:
        return None
    return QI_SENSING_THRESHOLDS[next_layer - 1]


def cultivation_gain(base: int, qualification: Mapping[str, int]) -> int:
    """Apply the integer version of ``base * (1 + insight / 200)``."""

    insight = max(0, int(qualification.get("insight", 0)))
    return (base * (200 + insight)) // 200


def can_advance_layer(realm_key: str, layer: int, cultivation: int) -> bool:
    threshold = next_layer_threshold(realm_key, layer)
    return threshold is not None and cultivation >= threshold

