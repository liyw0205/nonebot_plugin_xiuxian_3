"""Content-backed rules for the common secret realms."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import local_reputation_maximum
from ..utils.player import PLAYER_RESOURCE_FIELDS
from ..utils.randomness import deterministic_weighted_choice
from .secret_realm_models import SecretRealmDefinition


_NODE_KEYS = frozenset({"resource", "encounter", "choice"})
_NODE_ALIASES = {
    "资源": "resource",
    "resource": "resource",
    "遭遇": "encounter",
    "encounter": "encounter",
    "选择": "choice",
    "choice": "choice",
}
_REALM_ALIASES = {
    "instance.secret_realm.boundary_rift": "instance.secret_realm.boundary_rift",
    "instance.secret_realm.ancient_domain": "instance.secret_realm.ancient_domain",
    "instance.secret_realm.ancestral_hall": "instance.secret_realm.ancestral_hall",
    "instance.secret_realm.void_ruins": "instance.secret_realm.void_ruins",
    "instance.secret_realm.time_fort": "instance.secret_realm.time_fort",
    "instance.secret_realm.dao_origin": "instance.secret_realm.dao_origin",
    "instance.secret_realm.heaven_echo": "instance.secret_realm.heaven_echo",
    "界隙裂隙": "instance.secret_realm.boundary_rift",
    "界隙裂隙秘境": "instance.secret_realm.boundary_rift",
    "远古洞天": "instance.secret_realm.ancient_domain",
    "远古洞天秘境": "instance.secret_realm.ancient_domain",
    "祖灵殿": "instance.secret_realm.ancestral_hall",
    "祖灵殿秘境": "instance.secret_realm.ancestral_hall",
    "虚空遗迹": "instance.secret_realm.void_ruins",
    "虚空遗迹秘境": "instance.secret_realm.void_ruins",
    "时序堡垒": "instance.secret_realm.time_fort",
    "时序堡垒秘境": "instance.secret_realm.time_fort",
    "道源秘境": "instance.secret_realm.dao_origin",
    "道源秘境副本": "instance.secret_realm.dao_origin",
    "天劫回音": "instance.secret_realm.heaven_echo",
    "天劫回音秘境": "instance.secret_realm.heaven_echo",
}


@lru_cache(maxsize=1)
def _default_content() -> ContentBundle:
    return bundled_content()


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else _default_content()


def _positive_int(value: Any, field: str, key: str, *, allow_zero: bool = False) -> int:
    valid = isinstance(value, int) and not isinstance(value, bool) and (value >= 0 if allow_zero else value > 0)
    if not valid:
        bound = "non-negative" if allow_zero else "positive"
        raise ContentError(f"secret realm {key} {field} must be a {bound} integer")
    return value


def _reward_map(row: Any, field: str, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(row, dict) or not row:
        raise ContentError(f"secret realm {key} {field} must be a non-empty object")
    result: dict[str, int] = {}
    for reward_key, quantity in row.items():
        if not isinstance(reward_key, str) or not reward_key:
            raise ContentError(f"secret realm {key} {field} contains an invalid reward key")
        result[reward_key] = _positive_int(quantity, f"{field}.{reward_key}", key)
        _validate_reward_key(reward_key, key, bundle)
        if reward_key.startswith("codex.") and quantity != 1:
            raise ContentError(f"secret realm {key} codex rewards must have quantity 1")
    return result


def _validate_reward_key(reward_key: str, realm_key: str, bundle: ContentBundle) -> None:
    if reward_key == "spirit_stones":
        return
    if reward_key in PLAYER_RESOURCE_FIELDS and not reward_key.endswith("_max"):
        return
    if reward_key.startswith("item."):
        if bundle.get("item", reward_key, include_locked=False) is None:
            raise ContentError(f"secret realm {realm_key} references an inactive item {reward_key}")
        return
    if reward_key.startswith("codex."):
        if bundle.get("codex_entry", reward_key, include_locked=False) is None:
            raise ContentError(f"secret realm {realm_key} references an inactive codex entry {reward_key}")
        return
    if reward_key.startswith("local."):
        try:
            local_reputation_maximum(reward_key, bundle)
        except (ContentError, ValueError) as exc:
            raise ContentError(f"secret realm {realm_key} references an invalid local reputation {reward_key}") from exc
        return
    raise ContentError(f"secret realm {realm_key} has unsupported reward key {reward_key!r}")


def _definition(row: dict[str, Any], bundle: ContentBundle) -> SecretRealmDefinition:
    key = row.get("key")
    if not isinstance(key, str) or not key.startswith("instance.secret_realm."):
        raise ContentError(f"secret realm {key!r} has an invalid key")
    if row.get("record_type") != "common":
        raise ContentError(f"secret realm {key} must use record_type=common")
    label = row.get("name")
    if not isinstance(label, str) or not label.strip():
        raise ContentError(f"secret realm {key} requires a name")
    description = row.get("desc")
    if not isinstance(description, str) or not description.strip():
        raise ContentError(f"secret realm {key} requires a description")
    required_realm = row.get("required_realm")
    if not isinstance(required_realm, str):
        raise ContentError(f"secret realm {key} has an invalid required_realm")
    if bundle.get("realm", required_realm, include_locked=False) is None:
        raise ContentError(f"secret realm {key} references an inactive realm {required_realm}")
    required_layer = _positive_int(row.get("required_layer"), "required_layer", key)
    location_key = row.get("location_key")
    if not isinstance(location_key, str) or bundle.get("location", location_key, include_locked=False) is None:
        raise ContentError(f"secret realm {key} references an inactive location")
    stamina_cost = _positive_int(row.get("stamina_cost"), "stamina_cost", key, allow_zero=True)
    ticket_key = row.get("ticket_key")
    if ticket_key is not None:
        if not isinstance(ticket_key, str) or bundle.get("item", ticket_key, include_locked=False) is None:
            raise ContentError(f"secret realm {key} references an inactive ticket")
    ticket_quantity = _positive_int(row.get("ticket_quantity"), "ticket_quantity", key, allow_zero=True)
    if (ticket_key is None) != (ticket_quantity == 0):
        raise ContentError(f"secret realm {key} ticket key and quantity must be provided together")
    nodes = row.get("node_keys")
    if not isinstance(nodes, list) or not nodes or any(not isinstance(node, str) or node not in _NODE_KEYS for node in nodes):
        raise ContentError(f"secret realm {key} has invalid node_keys")
    if nodes[0] != "resource" or "encounter" not in nodes:
        raise ContentError(f"secret realm {key} must begin with resource and contain encounter")
    enemy_key = row.get("enemy_key")
    if not isinstance(enemy_key, str) or bundle.get("enemy", enemy_key, include_locked=False) is None:
        raise ContentError(f"secret realm {key} references an inactive enemy")
    first_reward = _reward_map(row.get("first_reward"), "first_reward", key, bundle)
    outcomes = row.get("repeat_reward_pool")
    if not isinstance(outcomes, list) or not outcomes:
        raise ContentError(f"secret realm {key} requires repeat_reward_pool")
    normalized_outcomes: list[tuple[int, dict[str, int]]] = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise ContentError(f"secret realm {key} repeat outcome {index} must be an object")
        weight = _positive_int(outcome.get("weight"), f"repeat_reward_pool[{index}].weight", key)
        no_reward = outcome.get("no_reward")
        if no_reward is not None:
            if no_reward is not True or "rewards" in outcome:
                raise ContentError(f"secret realm {key} repeat outcome {index} has an invalid no_reward marker")
            rewards = {}
        else:
            rewards = _reward_map(
                outcome.get("rewards"),
                f"repeat_reward_pool[{index}].rewards",
                key,
                bundle,
            )
        normalized_outcomes.append((weight, rewards))
    quota_period = row.get("quota_period")
    if quota_period not in {"day", "week"}:
        raise ContentError(f"secret realm {key} has an invalid quota_period")
    quota_limit = _positive_int(row.get("quota_limit"), "quota_limit", key)
    expiry_seconds = _positive_int(row.get("expiry_seconds"), "expiry_seconds", key)
    reputation_key = row.get("reputation_key")
    if reputation_key is not None and (not isinstance(reputation_key, str) or not reputation_key.startswith("local.")):
        raise ContentError(f"secret realm {key} has an invalid reputation_key")
    reward_reputation_keys = {
        reward_key
        for reward in (first_reward, *(result for _, result in normalized_outcomes))
        for reward_key in reward
        if reward_key.startswith("local.")
    }
    if len(reward_reputation_keys) > 1 or reward_reputation_keys != ({reputation_key} if reputation_key else set()):
        raise ContentError(f"secret realm {key} reputation_key does not match its rewards")
    aliases = row.get("aliases")
    if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        raise ContentError(f"secret realm {key} aliases must be non-empty strings")
    normalized_aliases = [alias.strip() for alias in aliases]
    if len(set(normalized_aliases)) != len(normalized_aliases) or any(
        alias in {key, label.strip()} for alias in normalized_aliases
    ):
        raise ContentError(f"secret realm {key} has duplicate aliases")
    return SecretRealmDefinition(
        key=key,
        label=label.strip(),
        description=description.strip(),
        required_realm=required_realm,
        required_layer=required_layer,
        location_key=location_key,
        stamina_cost=stamina_cost,
        ticket_key=ticket_key,
        ticket_quantity=ticket_quantity,
        node_keys=tuple(nodes),
        enemy_key=enemy_key,
        first_reward=first_reward,
        repeat_reward_pool=tuple(normalized_outcomes),
        quota_period=quota_period,
        quota_limit=quota_limit,
        expiry_seconds=expiry_seconds,
        reputation_key=reputation_key,
    )


def secret_realm_definitions(content: ContentBundle | None = None, *, include_locked: bool = False) -> dict[str, SecretRealmDefinition]:
    bundle = _bundle(content)
    result: dict[str, SecretRealmDefinition] = {}
    selectors: set[str] = set(_REALM_ALIASES)
    for row in bundle.list("secret_realm", include_locked=include_locked):
        if row.get("record_type") != "common":
            continue
        definition = _definition(row, bundle)
        if definition.key in result:
            raise ContentError(f"duplicate secret realm definition {definition.key}")
        aliases = row["aliases"]
        row_selectors = {definition.key, definition.label, *(alias.strip() for alias in aliases)}
        if selectors & row_selectors:
            raise ContentError(f"secret realm {definition.key} has a duplicate name or alias")
        selectors.update(row_selectors)
        result[definition.key] = definition
    if not result:
        raise ContentError("no common secret realm definitions are active")
    return result


def repeat_reward(definition: SecretRealmDefinition, seed: str) -> dict[str, int]:
    return dict(deterministic_weighted_choice(definition.repeat_reward_pool, seed))


def resolve_secret_realm(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    bundle = _bundle(content)
    aliases = dict(_REALM_ALIASES)
    for definition in secret_realm_definitions(content).values():
        aliases[definition.key] = definition.key
        aliases[definition.label] = definition.key
        row = bundle.require("secret_realm", definition.key, include_locked=False)
        for alias in row.get("aliases", []):
            if isinstance(alias, str) and alias.strip():
                aliases[alias.strip()] = definition.key
    return aliases.get(normalized)


def resolve_node(value: str) -> str | None:
    return _NODE_ALIASES.get(value.strip())


def secret_realm_definition(key: str, content: ContentBundle | None = None, *, include_locked: bool = False) -> SecretRealmDefinition:
    try:
        return secret_realm_definitions(content, include_locked=include_locked)[key]
    except KeyError as exc:
        raise ValueError(f"unsupported secret realm: {key}") from exc


def realm_at_least(
    realm_key: str,
    layer: int,
    required_realm: str,
    required_layer: int,
    content: ContentBundle | None = None,
) -> bool:
    bundle = _bundle(content)
    current = bundle.get("realm", str(realm_key), include_locked=False)
    required = bundle.get("realm", required_realm, include_locked=False)
    if current is None or required is None:
        return False
    current_rank = _positive_int(current.get("rank"), "rank", str(realm_key), allow_zero=True)
    required_rank = _positive_int(required.get("rank"), "rank", required_realm, allow_zero=True)
    return (current_rank, int(layer)) >= (required_rank, int(required_layer))


__all__ = ["realm_at_least", "repeat_reward", "resolve_node", "resolve_secret_realm", "secret_realm_definition", "secret_realm_definitions"]
