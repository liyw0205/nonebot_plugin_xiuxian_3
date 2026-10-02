"""Stable event keys and command vocabulary for cross-realm events."""

BEAST_TRADE_EVENT_KEY = "event.beast_trade"
BOUNDARY_RIFT_EVENT_KEY = "event.boundary_rift"

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


__all__ = [
    "BEAST_TRADE_ACTION_VALUES",
    "BEAST_TRADE_EVENT_KEY",
    "BOUNDARY_RIFT_ACTION_VALUES",
    "BOUNDARY_RIFT_EVENT_KEY",
]
