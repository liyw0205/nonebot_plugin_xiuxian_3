"""Pure, versioned rules for v0.1 secret realms."""

from __future__ import annotations

from .secret_realm_models import SecretRealmDefinition

RULE_VERSION = "adventures-0.1.1"
CONTENT_VERSION = "content-0.1"
V02_RULE_VERSION = "adventures-0.2.0"
V02_CONTENT_VERSION = "content-0.2"

MIST_GROTTO = SecretRealmDefinition(
    key="instance.secret_realm.mist_grotto",
    label="雾隐秘境",
    required_realm="qi_gathering",
    required_layer=4,
    location_key="cave.mist_grotto",
    stamina_cost=10,
    ticket_key="item.cave_pass_basic",
    ticket_quantity=1,
    node_keys=("resource", "encounter", "choice"),
    enemy_key="enemy.mist_guardian",
    first_reward={"spirit_stones": 80, "item.material.mist_core": 2, "codex.instance.mist_grotto": 1},
    repeat_reward={"item.material.mist_core": 1},
    quota_period="week",
    quota_limit=2,
    rule_version=RULE_VERSION,
    content_version=CONTENT_VERSION,
)

SPRING_PATH = SecretRealmDefinition(
    key="instance.secret_realm.spring_path",
    label="灵泉小径",
    required_realm="qi_sensing",
    required_layer=3,
    location_key="xuantian.spirit_field",
    stamina_cost=6,
    ticket_key=None,
    ticket_quantity=0,
    node_keys=("resource", "encounter"),
    enemy_key="enemy.spring_wisp",
    first_reward={"item.herb.spirit_leaf": 2, "local_reputation": 5},
    repeat_reward={"item.herb.spirit_leaf": 1},
    quota_period="day",
    quota_limit=1,
    rule_version=RULE_VERSION,
    content_version=CONTENT_VERSION,
)

MIST_DEPTH_2 = SecretRealmDefinition(
    key="instance.secret_realm.mist_depth_2",
    label="雾隐洞天二层秘境",
    required_realm="golden_core",
    required_layer=1,
    location_key="cave.mist_grotto_2",
    stamina_cost=15,
    ticket_key="item.cave_pass_advanced",
    ticket_quantity=1,
    node_keys=("resource", "encounter", "choice", "encounter", "choice"),
    enemy_key="enemy.mist_elite",
    first_reward={"item.weapon.cloud_sword": 1},
    repeat_reward={"item.material.cloud_iron": 1},
    quota_period="week",
    quota_limit=1,
    rule_version=V02_RULE_VERSION,
    content_version=V02_CONTENT_VERSION,
)

CLOUD_BOAT = SecretRealmDefinition(
    key="instance.secret_realm.cloud_boat",
    label="云舟秘境",
    required_realm="golden_core",
    required_layer=1,
    location_key="xuantian.floating_boat",
    stamina_cost=12,
    ticket_key="item.ticket.cloud_boat_fragment",
    ticket_quantity=1,
    node_keys=("resource", "encounter", "choice"),
    enemy_key="enemy.cloud_boat_guardian",
    first_reward={"codex.instance.cloud_boat": 1, "local_reputation": 12},
    repeat_reward={"item.ticket.cloud_boat_fragment": 1},
    quota_period="week",
    quota_limit=2,
    rule_version=V02_RULE_VERSION,
    content_version=V02_CONTENT_VERSION,
)

DEFINITIONS = {item.key: item for item in (MIST_GROTTO, SPRING_PATH, MIST_DEPTH_2, CLOUD_BOAT)}
ALIASES = {
    **{key: key for key in DEFINITIONS},
    "雾隐秘境": MIST_GROTTO.key,
    "雾隐洞天秘境": MIST_GROTTO.key,
    "灵泉小径": SPRING_PATH.key,
    "灵泉秘境": SPRING_PATH.key,
    "雾隐洞天二层秘境": MIST_DEPTH_2.key,
    "洞天二层秘境": MIST_DEPTH_2.key,
    "云舟秘境": CLOUD_BOAT.key,
}

NODE_ALIASES = {
    "资源": "resource",
    "resource": "resource",
    "遭遇": "encounter",
    "encounter": "encounter",
    "选择": "choice",
    "choice": "choice",
}


def resolve_secret_realm(value: str) -> str | None:
    return ALIASES.get(value.strip())


def resolve_node(value: str) -> str | None:
    return NODE_ALIASES.get(value.strip())


def secret_realm_definition(key: str) -> SecretRealmDefinition:
    try:
        return DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported secret realm: {key}") from exc


def realm_at_least(realm_key: str, layer: int, required_realm: str, required_layer: int) -> bool:
    ranks = {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }
    return (ranks.get(str(realm_key), -1), int(layer)) >= (ranks.get(required_realm, 99), int(required_layer))


__all__ = [
    "ALIASES",
    "CONTENT_VERSION",
    "DEFINITIONS",
    "NODE_ALIASES",
    "RULE_VERSION",
    "V02_CONTENT_VERSION",
    "V02_RULE_VERSION",
    "realm_at_least",
    "resolve_node",
    "resolve_secret_realm",
    "secret_realm_definition",
]
