"""Pure rules for the mentor relationship slice."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum


MENTOR_INVITATION_TTL_SECONDS = 24 * 60 * 60
MENTOR_MAX_APPRENTICES = 3
MENTOR_MASTER_REALM = "foundation"
MENTOR_MASTER_MIN_LAYER = 4
MENTOR_APPRENTICE_REALMS = frozenset({"mortal", "qi_sensing", "qi_gathering"})
MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER = 6
_MASTER_REALM_RANKS = {
    "foundation": 3,
    "golden_core": 4,
    "nascent_soul": 5,
    "soul_transformation": 6,
    "void_refining": 7,
    "dao_union": 8,
    "tribulation": 9,
}


@dataclass(frozen=True, slots=True)
class MentorGraduationDefinition:
    key: str
    required_realm: str
    required_rank: int
    required_layer: int
    local_reputation_key: str
    local_reputation_maximum: int
    apprentice_local_reputation: int
    master_contribution: int
    service_reputation: int

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


_GRADUATION_FIELDS = frozenset(field.name for field in fields(MentorGraduationDefinition))
_GRADUATION_NUMBER_FIELDS = _GRADUATION_FIELDS - {"key", "required_realm", "local_reputation_key"}


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"mentor graduation {name} is invalid")
    return value


def mentor_graduation_from_snapshot(value: object) -> MentorGraduationDefinition:
    if not isinstance(value, Mapping) or set(value) != _GRADUATION_FIELDS:
        raise ValueError("mentor graduation snapshot fields are incomplete or unsupported")
    if value["key"] != "social.mentor_graduation":
        raise ValueError("mentor graduation key is invalid")
    for name in ("required_realm", "local_reputation_key"):
        item = value[name]
        if not isinstance(item, str) or not item or item != item.strip():
            raise ValueError(f"mentor graduation {name} is invalid")
    reputation_key = value["local_reputation_key"]
    if not reputation_key.startswith("local.") or not reputation_key.removeprefix("local.").strip():
        raise ValueError("mentor graduation local_reputation_key is invalid")
    for name in _GRADUATION_NUMBER_FIELDS:
        _integer(value[name], name, 1 if name == "local_reputation_maximum" else 0)
    return MentorGraduationDefinition(**dict(value))


def _realm_bounds(row: Mapping[str, Any], realm_key: str) -> tuple[int, int, int]:
    try:
        rank = _integer(row["rank"], "rank")
        minimum = _integer(row["layer_min"], "layer_min")
        maximum = _integer(row["layer_max"], "layer_max")
        if maximum < minimum:
            raise ValueError("layer_max is below layer_min")
    except (KeyError, ValueError) as exc:
        raise ContentError(f"invalid mentor graduation realm {realm_key}: {exc}") from exc
    return rank, minimum, maximum


def mentor_graduation_definition(content: ContentBundle | None = None) -> MentorGraduationDefinition:
    bundle = content if content is not None else bundled_content()
    try:
        row = bundle.require("social_interaction", "social.mentor_graduation", include_locked=False)
    except KeyError as exc:
        raise ContentError("missing or inactive social.mentor_graduation content") from exc
    try:
        for name in ("name", "desc"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError(f"{name} is invalid")
        snapshot = {
            name: row[name] for name in _GRADUATION_FIELDS
            if name not in {"required_rank", "local_reputation_maximum"}
        }
        required_realm = snapshot["required_realm"]
        if not isinstance(required_realm, str) or not required_realm or required_realm != required_realm.strip():
            raise ValueError("required_realm is invalid")
        realm = bundle.require("realm", required_realm, include_locked=False)
        rank, minimum, maximum = _realm_bounds(realm, required_realm)
        snapshot["required_rank"] = rank
        snapshot["local_reputation_maximum"] = local_reputation_maximum(snapshot["local_reputation_key"], bundle)
        definition = mentor_graduation_from_snapshot(snapshot)
        if not minimum <= definition.required_layer <= maximum:
            raise ValueError("required_layer is outside required_realm")
        return definition
    except (KeyError, ValueError) as exc:
        raise ContentError(f"invalid social.mentor_graduation content: {exc}") from exc


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


def is_graduation_ready(
    stage: str,
    realm_key: str,
    realm_layer: int,
    definition: MentorGraduationDefinition,
    content: ContentBundle | None = None,
) -> bool:
    if stage != "cultivator" or not isinstance(realm_key, str):
        return False
    if isinstance(realm_layer, bool) or not isinstance(realm_layer, int):
        return False
    bundle = content if content is not None else bundled_content()
    realm = bundle.get("realm", realm_key, include_locked=False)
    if realm is None:
        return False
    rank, minimum, maximum = _realm_bounds(realm, realm_key)
    if not minimum <= realm_layer <= maximum:
        return False
    return (rank, realm_layer) >= (definition.required_rank, definition.required_layer)


__all__ = [
    "MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER",
    "MENTOR_APPRENTICE_REALMS",
    "MENTOR_INVITATION_TTL_SECONDS",
    "MENTOR_MASTER_MIN_LAYER",
    "MENTOR_MASTER_REALM",
    "MENTOR_MAX_APPRENTICES",
    "MentorGraduationDefinition",
    "is_apprentice_eligible",
    "is_graduation_ready",
    "is_master_eligible",
    "mentor_graduation_definition",
    "mentor_graduation_from_snapshot",
]
