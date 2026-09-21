# 世界域：用例与验收

## 用例

- `get_location(player_id)` -> 当前地点和可用动作。
- `preview_travel(player_id, destination)` -> 条件、费用、时间，不写资产。
- `start_travel(player_id, destination, operation_id)` -> 移动会话。
- `settle_travel(travel_id, operation_id)` -> 新位置和途中事件。
- `leave_closed_location(player_id, operation_id)` -> 撤离结果。

## 错误码

`LOCATION_NOT_FOUND`、`LOCATION_LOCKED`、`TRAVEL_BUSY`、`PLAYER_OCCUPIED`、`TRAVEL_RESOURCE_INSUFFICIENT`、`TRAVEL_ROUTE_INVALID`。

## 验收

入口不满足时不扣资源；重复移动不重复扣费；到达重试不重复事件；地点规则更新不改变已完成会话；未知地点不可进入资产写入流程。