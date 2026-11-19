"""Content-backed recovery and resource capacity rules."""

from ..content import ContentBundle, ContentError, bundled_content


def bloodline_recovery_rule(content: ContentBundle | None = None) -> dict:
    bundle = content if content is not None else bundled_content()
    rule = bundle.get("advancement_rule", "recovery.bloodline", include_locked=False)
    if rule is None:
        raise ContentError("missing active recovery.bloodline rule")
    for field in ("per_period", "maximum", "required_layer"):
        value = rule.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
            raise ContentError(f"recovery.bloodline has invalid {field}")
    realm_key = rule.get("required_realm")
    realm = bundle.get("realm", realm_key, include_locked=False) if isinstance(realm_key, str) else None
    if realm is None or rule["required_layer"] > realm["layer_max"]:
        raise ContentError("recovery.bloodline has invalid required_realm or required_layer")
    if rule["per_period"] > rule["maximum"]:
        raise ContentError("recovery.bloodline per_period exceeds maximum")
    return rule


def endgame_stamina_rule(content: ContentBundle | None = None) -> dict:
    bundle = content if content is not None else bundled_content()
    rule = bundle.get("advancement_rule", "recovery.endgame_stamina", include_locked=False)
    if rule is None:
        raise ContentError("missing active recovery.endgame_stamina rule")
    capacity = rule.get("minimum_capacity")
    layer = rule.get("required_layer")
    realm_key = rule.get("required_realm")
    realm = bundle.get("realm", realm_key, include_locked=False) if isinstance(realm_key, str) else None
    if (
        isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0
        or isinstance(layer, bool) or not isinstance(layer, int)
        or realm is None or not 1 <= layer <= realm["layer_max"]
    ):
        raise ContentError("recovery.endgame_stamina has invalid capacity or realm qualification")
    return rule
