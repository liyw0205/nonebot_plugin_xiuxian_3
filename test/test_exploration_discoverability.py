"""Every open exploration mode must be discoverable from its own location.

Location actions are what the world layer exposes for a place, so a mode that
no location lists is invisible to players, and a location that lists a mode
belonging to another place offers an activity that cannot run there.
"""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

DATA = Path(__file__).parents[1] / "data"


def test_every_open_exploration_mode_is_listed_on_its_own_location() -> None:
    bundle = ContentBundle.load(DATA)
    locations = {row["key"]: row for row in bundle.list("location")}
    missing = []
    for mode in bundle.list("exploration_mode"):
        if mode.get("status") != "open":
            continue
        location_key = mode["location_key"]
        actions = locations[location_key].get("actions") or []
        if mode["key"] not in actions:
            missing.append((mode["key"], location_key))
    assert missing == [], f"exploration modes not discoverable: {missing}"


def test_locations_do_not_advertise_another_locations_mode() -> None:
    bundle = ContentBundle.load(DATA)
    mismatched = []
    for location in bundle.list("location"):
        for action in location.get("actions") or []:
            if not action.startswith("explore."):
                continue
            mode = bundle.get("exploration_mode", action)
            if mode is None:
                continue
            if mode["location_key"] != location["key"]:
                mismatched.append((location["key"], action, mode["location_key"]))
    assert mismatched == [], f"locations advertise a foreign mode: {mismatched}"


def test_void_portal_no_longer_advertises_the_first_route_mode() -> None:
    """The regression that motivated this slice."""

    bundle = ContentBundle.load(DATA)
    portal = bundle.require("location", "void.portal")
    assert "explore.void_route" not in (portal.get("actions") or [])
    first_route = bundle.require("location", "void.first_route")
    assert "explore.void_route" in (first_route.get("actions") or [])
