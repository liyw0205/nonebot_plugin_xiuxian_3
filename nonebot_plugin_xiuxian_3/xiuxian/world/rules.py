"""Movement definitions for the first world slice."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from ..content import ContentBundle, bundled_content
from .cloud_rules import BEAST_INTRO_FLAG


CAVE_LOCATION = "cave.mist_grotto"
CAVE_PASS = "item.cave_pass_basic"
BEAST_HILLS_REQUIRED_REPUTATION = 200


@dataclass(frozen=True, slots=True)
class DestinationDefinition:
    key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    currency_cost: int
    required_realm: str | None = None
    required_layer: int = 0
    pass_key: str | None = None
    pass_quantity: int = 0
    source_locations: tuple[str, ...] = ()
    required_dao_fruit_progress: int = 0
    daily_start_limit: int = 0
    required_endgame_status: str | None = None
    required_intro_flag: str | None = None
    consume_pass_on_arrival: bool = False
    required_faction: str | None = None
    required_faction_reputation: int = 0
    pass_exempt_source_locations: tuple[str, ...] = ()
    requires_selected_domain: bool = False


DESTINATIONS = {
    "xuantian.new_town": DestinationDefinition(
        "xuantian.new_town", "青石镇", 30, 1, 0,
        source_locations=("xuantian.outskirts", "xuantian.sect_gate", "xuantian.spirit_field", "xuantian.cloud_mine"),
    ),
    "xuantian.outskirts": DestinationDefinition(
        "xuantian.outskirts", "玄天近郊", 30, 2, 0,
        source_locations=("xuantian.new_town",),
    ),
    "xuantian.sect_gate": DestinationDefinition(
        "xuantian.sect_gate", "宗门山门", 60, 3, 0,
        required_realm="qi_gathering", required_layer=4,
        source_locations=("xuantian.new_town", "xuantian.outskirts"),
    ),
    "xuantian.spirit_field": DestinationDefinition(
        "xuantian.spirit_field", "灵泉谷", 90, 4, 0,
        required_realm="qi_sensing", required_layer=2,
        source_locations=("xuantian.new_town", "xuantian.outskirts"),
    ),
    CAVE_LOCATION: DestinationDefinition(
        CAVE_LOCATION, "雾隐洞天·一层", 120, 5, 10,
        required_realm="qi_gathering", required_layer=4,
        pass_key=CAVE_PASS, pass_quantity=1,
        source_locations=("xuantian.new_town", "xuantian.sect_gate", "xuantian.spirit_field"),
    ),
    "dao.origin_gate": DestinationDefinition(
        "dao.origin_gate", "道源门", 60 * 60, 20, 0,
        required_realm="dao_union", required_layer=6,
        pass_key="item.dao_fruit_fragment", pass_quantity=2,
        source_locations=("void.archive_ruins",),
        required_dao_fruit_progress=470,
        daily_start_limit=1,
    ),
    "tribulation.sky_terrace": DestinationDefinition(
        "tribulation.sky_terrace", "天劫台", 30 * 60, 0, 0,
        required_realm="tribulation", required_layer=3,
        pass_key="item.tribulation_token", pass_quantity=1,
        source_locations=("dao.origin_gate",),
    ),
    "ascension.heaven_path": DestinationDefinition(
        "ascension.heaven_path", "飞升路", 90 * 60, 0, 0,
        source_locations=("tribulation.sky_terrace",),
        required_endgame_status="ascension_ready",
    ),
    "ascension.left_world_hall": DestinationDefinition(
        "ascension.left_world_hall", "留界殿", 30 * 60, 10, 0,
        source_locations=("ascension.heaven_path",),
        required_endgame_status="remained_in_world",
    ),
    "xuantian.cloud_city": DestinationDefinition(
        "xuantian.cloud_city", "玄天界·云城", 3 * 60, 8, 0,
        required_realm="golden_core", required_layer=1,
        source_locations=("xuantian.new_town", "xuantian.outskirts", "xuantian.sect_gate"),
    ),
    "xuantian.cloud_mine": DestinationDefinition(
        "xuantian.cloud_mine", "云铁矿区", 2 * 60, 6, 0,
        required_realm="foundation", required_layer=1,
        source_locations=("xuantian.cloud_city", "xuantian.new_town"),
    ),
    "xuantian.floating_boat": DestinationDefinition(
        "xuantian.floating_boat", "云舟渡口", 60, 0, 500,
        required_realm="foundation", required_layer=1,
        source_locations=("xuantian.cloud_city",),
    ),
    "cave.mist_grotto_2": DestinationDefinition(
        "cave.mist_grotto_2", "雾隐洞天·二层", 3 * 60, 15, 0,
        required_realm="golden_core", required_layer=1,
        pass_key="item.cave_pass_advanced", pass_quantity=1,
        source_locations=("xuantian.floating_boat",),
    ),
    "xuantian.array_hall": DestinationDefinition(
        "xuantian.array_hall", "玄天阵堂", 60, 3, 0,
        required_realm="qi_gathering", required_layer=1,
        source_locations=("xuantian.cloud_city", "xuantian.sect_gate"),
    ),
    "demon.abyss_gate": DestinationDefinition(
        "demon.abyss_gate", "魔界·深渊门", 2 * 60, 10, 0,
        required_realm="foundation", required_layer=1,
        source_locations=("xuantian.floating_boat",),
    ),
    "demon.fallen_ruins": DestinationDefinition(
        "demon.fallen_ruins", "魔界·堕落遗迹", 8 * 60, 20, 0,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("demon.abyss_gate",),
        required_intro_flag="access.demon_abyss_gate",
    ),
    "demon.abyss_market": DestinationDefinition(
        "demon.abyss_market", "魔界·魔渊集市", 5 * 60, 12, 500,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("demon.abyss_gate", "demon.fallen_ruins"),
        required_faction="demon", required_faction_reputation=200,
    ),
    "beast.ten_thousand_hills": DestinationDefinition(
        "beast.ten_thousand_hills", "妖界·万兽山", 5 * 60, 12, 0,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("xuantian.floating_boat",),
        required_faction="beast", required_faction_reputation=200,
    ),
    "beast.ancestral_lake": DestinationDefinition(
        "beast.ancestral_lake", "妖界·祖灵湖", 10 * 60, 25, 0,
        required_realm="soul_transformation", required_layer=1,
        source_locations=("beast.ten_thousand_hills",),
        required_faction="beast", required_faction_reputation=3000,
    ),
    "xuantian.domain_front": DestinationDefinition(
        "xuantian.domain_front", "玄天界·领域前线", 5 * 60, 20, 0,
        required_realm="soul_transformation", required_layer=1,
        source_locations=("xuantian.new_town", "xuantian.sect_gate", "xuantian.array_hall", "xuantian.war_front", "cave.boundary_realm"),
        requires_selected_domain=True,
    ),
    "beast.three_realms_trade_port": DestinationDefinition(
        "beast.three_realms_trade_port", "妖界·三界贸易口", 3 * 60, 8, 0,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("beast.ten_thousand_hills",),
        required_faction="beast", required_faction_reputation=200,
    ),
    "xuantian.war_front": DestinationDefinition(
        "xuantian.war_front", "玄天·魔界战场", 5 * 60, 15, 0,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("xuantian.new_town", "xuantian.outskirts"),
    ),
    "cave.boundary_realm": DestinationDefinition(
        "cave.boundary_realm", "界隙秘境", 10 * 60, 30, 0,
        required_realm="nascent_soul", required_layer=1,
        source_locations=("cave.mist_grotto_2", "demon.fallen_ruins", "beast.ten_thousand_hills", "xuantian.war_front", "void.archive_ruins"),
        required_intro_flag="story.mainline.three_realms",
        pass_exempt_source_locations=("void.archive_ruins",),
    ),
    "void.portal": DestinationDefinition(
        "void.portal", "虚空门户", 5 * 60, 10, 0,
        required_realm="soul_transformation", required_layer=1,
        source_locations=("cave.boundary_realm",),
    ),
}

ALIASES = {
    "新手城": "xuantian.new_town",
    "青石镇": "xuantian.new_town",
    "近郊": "xuantian.outskirts",
    "玄天近郊": "xuantian.outskirts",
    "宗门山门": "xuantian.sect_gate",
    "灵泉谷": "xuantian.spirit_field",
    "雾隐洞天": CAVE_LOCATION,
    "雾隐洞天一层": CAVE_LOCATION,
    "雾隐洞天·一层": CAVE_LOCATION,
    "道源门": "dao.origin_gate",
    "天劫台": "tribulation.sky_terrace",
    "tribulation.sky_terrace": "tribulation.sky_terrace",
    "飞升路": "ascension.heaven_path",
    "ascension.heaven_path": "ascension.heaven_path",
    "留界殿": "ascension.left_world_hall",
    "ascension.left_world_hall": "ascension.left_world_hall",
    "云城": "xuantian.cloud_city",
    "玄天界·云城": "xuantian.cloud_city",
    "云铁矿区": "xuantian.cloud_mine",
    "云矿": "xuantian.cloud_mine",
    "云舟渡口": "xuantian.floating_boat",
    "云舟": "xuantian.floating_boat",
    "雾隐洞天二层": "cave.mist_grotto_2",
    "雾隐洞天·二层": "cave.mist_grotto_2",
    "玄天阵堂": "xuantian.array_hall",
    "阵堂": "xuantian.array_hall",
    "魔界深渊门": "demon.abyss_gate",
    "深渊门": "demon.abyss_gate",
    "魔界堕落遗迹": "demon.fallen_ruins",
    "堕落遗迹": "demon.fallen_ruins",
    "魔界魔渊集市": "demon.abyss_market",
    "魔渊集市": "demon.abyss_market",
    "契约集市": "demon.abyss_market",
    "妖界万兽山": "beast.ten_thousand_hills",
    "万兽山": "beast.ten_thousand_hills",
    "妖界祖灵湖": "beast.ancestral_lake",
    "祖灵湖": "beast.ancestral_lake",
    "玄天领域前线": "xuantian.domain_front",
    "领域前线": "xuantian.domain_front",
    "妖界三界贸易口": "beast.three_realms_trade_port",
    "三界贸易口": "beast.three_realms_trade_port",
    "三界互市": "beast.three_realms_trade_port",
    "贸易口": "beast.three_realms_trade_port",
    "魔界战场": "xuantian.war_front",
    "玄天魔界战场": "xuantian.war_front",
    "界隙秘境": "cave.boundary_realm",
    "界隙": "cave.boundary_realm",
    "边界秘境": "cave.boundary_realm",
    "虚空门户": "void.portal",
    "虚空门": "void.portal",
}


def _map_source_locations(destination: str, content: ContentBundle) -> tuple[str, ...]:
    """Read incoming map edges so travel has one source of truth."""

    sources: list[str] = []
    for region in content.list("world_region", include_locked=True):
        for connection in region.get("connections", []):
            if isinstance(connection, dict) and connection.get("to") == destination:
                source = connection.get("from")
                if isinstance(source, str) and source not in sources:
                    sources.append(source)
    return tuple(sources)


def _location_requirements(destination: str, content: ContentBundle) -> tuple[str | None, int, str | None, int]:
    location = content.get("location", destination, include_locked=True)
    if location is None:
        return None, 0, None, 0
    required_realm: str | None = None
    required_layer = 0
    required_faction: str | None = None
    required_faction_reputation = 0
    for requirement in location.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        kind = requirement.get("type")
        if kind == "realm" and isinstance(requirement.get("realm_key"), str):
            required_realm = requirement["realm_key"]
            required_layer = int(requirement.get("min_layer", 0))
        elif kind == "faction_reputation" and isinstance(requirement.get("faction"), str):
            required_faction = requirement["faction"]
            required_faction_reputation = int(requirement.get("minimum", requirement.get("min", 0)))
    return required_realm, required_layer, required_faction, required_faction_reputation


def _content_destination(destination: str, content: ContentBundle) -> DestinationDefinition | None:
    base = DESTINATIONS.get(destination)
    location = content.get("location", destination, include_locked=True)
    if location is None:
        return None
    if base is None:
        base = DestinationDefinition(
            key=destination,
            label=str(location.get("name") or destination),
            duration_seconds=0,
            stamina_cost=0,
            currency_cost=0,
        )
    travel = location.get("travel", {})
    if not isinstance(travel, dict):
        travel = {}
    required_realm, required_layer, required_faction, required_faction_reputation = _location_requirements(
        destination, content
    )
    # JSON controls mutable travel/content values.  Keep specialized endgame
    # gates from the existing contract when a location uses a story-only gate.
    requirements = location.get("requirements", [])
    for requirement in requirements if isinstance(requirements, list) else []:
        if isinstance(requirement, dict) and requirement.get("type") == "intro_flag":
            if isinstance(requirement.get("value"), str):
                base = replace(base, required_intro_flag=requirement["value"])
        if isinstance(requirement, dict) and requirement.get("type") == "endgame_status":
            if isinstance(requirement.get("value"), str):
                base = replace(base, required_endgame_status=requirement["value"])
    return replace(
        base,
        label=str(location.get("name") or base.label),
        duration_seconds=int(travel.get("duration_seconds", base.duration_seconds)),
        stamina_cost=int(travel.get("stamina", base.stamina_cost)),
        currency_cost=int(travel.get("spirit_stone", base.currency_cost)),
        required_realm=required_realm if required_realm is not None else base.required_realm,
        required_layer=required_layer if required_realm is not None else base.required_layer,
        pass_key=travel.get("item_key", base.pass_key),
        pass_quantity=int(travel.get("item_quantity", base.pass_quantity)),
        source_locations=_map_source_locations(destination, content) or base.source_locations,
        required_faction=required_faction or base.required_faction,
        required_faction_reputation=(
            required_faction_reputation if required_faction is not None else base.required_faction_reputation
        ),
    )


def resolve_destination(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    bundle = content or bundled_content()
    if bundle.has("location", normalized, include_locked=True):
        return normalized
    for location in bundle.list("location", include_locked=True):
        if normalized == location.get("name") or normalized in location.get("aliases", []):
            return str(location["key"])
    return ALIASES.get(normalized)


def destination_definition(destination: str, content: ContentBundle | None = None) -> DestinationDefinition:
    if content is not None:
        resolved = _content_destination(destination, content)
        if resolved is None:
            raise ValueError(f"destination is not registered in content: {destination}")
        return resolved
    try:
        return DESTINATIONS[destination]
    except KeyError as exc:
        raise ValueError(f"unsupported destination: {destination}") from exc


def destination_location_is_open(destination: str, content: ContentBundle | None) -> bool:
    if content is None:
        return True
    location = content.get("location", destination)
    return location is None or location.get("status") in {"active", "open"}


def realm_rank(realm_key: str) -> int:
    return {
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
    }.get(realm_key, -1)


def meets_realm(realm_key: str, layer: int, required_realm: str | None, required_layer: int) -> bool:
    if required_realm is None:
        return True
    return (realm_rank(realm_key), int(layer)) >= (realm_rank(required_realm), required_layer)


def beast_hills_entry_allowed(faction_reputation: int, intro_flags: Iterable[str]) -> bool:
    return int(faction_reputation) >= BEAST_HILLS_REQUIRED_REPUTATION or BEAST_INTRO_FLAG in set(intro_flags)
