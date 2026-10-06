"""Stable event keys and command vocabulary for cross-realm events."""

BEAST_TRADE_EVENT_KEY = "event.beast_trade"
BOUNDARY_RIFT_EVENT_KEY = "event.boundary_rift"
ANCIENT_DOMAIN_OPEN_EVENT_KEY = "event.ancient_domain_open"

BEAST_TRADE_ACTION_VALUES = {
    "贸易": "trade",
    "跨界贸易": "trade",
    "妖血": "blood",
    "提交妖血": "blood",
}
BOUNDARY_RIFT_ACTION_VALUES = {
    "路线": "route",
    "首领": "boss",
    "完成": "complete",
}
ANCIENT_DOMAIN_OPEN_ACTION_VALUES = {
    "完成": "complete",
    "远古洞天": "complete",
}


__all__ = [
    "BEAST_TRADE_ACTION_VALUES",
    "BEAST_TRADE_EVENT_KEY",
    "BOUNDARY_RIFT_ACTION_VALUES",
    "BOUNDARY_RIFT_EVENT_KEY",
    "ANCIENT_DOMAIN_OPEN_ACTION_VALUES",
    "ANCIENT_DOMAIN_OPEN_EVENT_KEY",
]
