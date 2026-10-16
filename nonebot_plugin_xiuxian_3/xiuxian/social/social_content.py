"""Content-backed contracts for the social rules."""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "social_interaction"
MENTOR_KEY = "social.mentor"
PARTY_KEY = "social.party"
SECT_KEY = "social.sect"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _record(bundle: ContentBundle, key: str) -> dict[str, Any]:
    try:
        row = bundle.require(KIND, key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing social_interaction content: {key}") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError(f"{key} status is not open")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    return row


def _positive(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return int(value)


def _realm(bundle: ContentBundle, realm_key: Any, key: str, field: str) -> None:
    if not isinstance(realm_key, str) or not realm_key.strip():
        raise ContentError(f"{key} {field} is invalid")
    try:
        bundle.require("realm", realm_key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"{key} {field} references unknown realm {realm_key}") from exc


def realm_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    """Rank of an open realm, read from the realm content instead of a table."""

    bundle = _bundle(content)
    try:
        row = bundle.require("realm", realm_key, include_locked=False)
    except KeyError:
        return -1
    rank = row.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ContentError(f"realm {realm_key} has no integer rank")
    return int(rank)


def mentor_rules_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, MENTOR_KEY)
    master_realm = row.get("master_realm")
    _realm(bundle, master_realm, MENTOR_KEY, "master_realm")
    apprentice_realms = row.get("apprentice_realms")
    if not isinstance(apprentice_realms, list) or not apprentice_realms:
        raise ContentError(f"{MENTOR_KEY} apprentice_realms must be a non-empty list")
    for realm_key in apprentice_realms:
        _realm(bundle, realm_key, MENTOR_KEY, "apprentice_realms")
    return {
        "key": MENTOR_KEY,
        "invitation_ttl_seconds": _positive(
            row.get("invitation_ttl_seconds"), "invitation_ttl_seconds", MENTOR_KEY
        ),
        "max_apprentices": _positive(
            row.get("max_apprentices"), "max_apprentices", MENTOR_KEY
        ),
        "master_realm": str(master_realm),
        "master_min_layer": _positive(
            row.get("master_min_layer"), "master_min_layer", MENTOR_KEY
        ),
        "apprentice_realms": tuple(str(realm_key) for realm_key in apprentice_realms),
        "apprentice_max_qi_gathering_layer": _positive(
            row.get("apprentice_max_qi_gathering_layer"),
            "apprentice_max_qi_gathering_layer",
            MENTOR_KEY,
        ),
    }


def party_definitions(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    row = _record(bundle, PARTY_KEY)
    definitions = row.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        raise ContentError(f"{PARTY_KEY} definitions must be a non-empty list")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(definitions):
        if not isinstance(item, dict):
            raise ContentError(f"{PARTY_KEY} definition {index} must be an object")
        party_type = item.get("party_type")
        if not isinstance(party_type, str) or not party_type.strip() or party_type in seen:
            raise ContentError(
                f"{PARTY_KEY} definition {index} has an invalid or duplicate party_type"
            )
        seen.add(party_type)
        min_members = _positive(item.get("min_members"), "min_members", party_type)
        max_members = _positive(item.get("max_members"), "max_members", party_type)
        if max_members < min_members:
            raise ContentError(f"{PARTY_KEY} {party_type} max_members is below min_members")
        distribution_key = item.get("distribution_key")
        if not isinstance(distribution_key, str) or not distribution_key.strip():
            raise ContentError(f"{PARTY_KEY} {party_type} has an invalid distribution_key")
        required_location = item.get("required_location")
        if required_location is not None:
            if not isinstance(required_location, str) or not required_location.strip():
                raise ContentError(
                    f"{PARTY_KEY} {party_type} has an invalid required_location"
                )
            try:
                bundle.require("location", required_location, include_locked=True)
            except KeyError as exc:
                raise ContentError(
                    f"{PARTY_KEY} {party_type} references unknown location {required_location}"
                ) from exc
        records.append(
            {
                "party_type": party_type,
                "min_members": min_members,
                "max_members": max_members,
                "confirmation_ttl_seconds": _positive(
                    item.get("confirmation_ttl_seconds"),
                    "confirmation_ttl_seconds",
                    party_type,
                ),
                "distribution_key": distribution_key,
                "required_location": required_location,
            }
        )
    return tuple(records)


def sect_rules_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_KEY)
    return {
        "key": SECT_KEY,
        "create_cost": _positive(row.get("create_cost"), "create_cost", SECT_KEY),
        "max_members": _positive(row.get("max_members"), "max_members", SECT_KEY),
        "warehouse_capacity": _positive(
            row.get("warehouse_capacity"), "warehouse_capacity", SECT_KEY
        ),
        "application_ttl_seconds": _positive(
            row.get("application_ttl_seconds"), "application_ttl_seconds", SECT_KEY
        ),
        "join_cooldown_seconds": _positive(
            row.get("join_cooldown_seconds"), "join_cooldown_seconds", SECT_KEY
        ),
    }


def party_aliases(content: ContentBundle | None = None) -> dict[str, str]:
    bundle = _bundle(content)
    row = _record(bundle, PARTY_KEY)
    aliases = row.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise ContentError(f"{PARTY_KEY} aliases must be an object")
    result: dict[str, str] = {}
    for alias, party_type in aliases.items():
        if (
            not isinstance(alias, str)
            or not alias.strip()
            or not isinstance(party_type, str)
            or not party_type.strip()
        ):
            raise ContentError(f"{PARTY_KEY} has an invalid alias")
        result[alias] = party_type
    return result


__all__ = [
    "KIND",
    "MENTOR_KEY",
    "PARTY_KEY",
    "mentor_rules_record",
    "party_aliases",
    "party_definitions",
    "realm_rank",
    "sect_rules_record",
]
