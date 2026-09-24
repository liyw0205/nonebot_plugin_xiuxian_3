# 世界域：用例与验收

## 用例

- `get_location(player_id)` -> 当前地点和可用动作。
- `preview_travel(player_id, destination)` -> 条件、费用、时间，不写资产。
- `start_travel(player_id, destination, operation_id)` -> 移动会话。
- `settle_travel(player_id, operation_id)` -> 新位置和途中事件；服务端从该角色唯一的运行中会话读取路线快照。
- `leave_closed_location(player_id, operation_id)` -> 撤离结果。

## 错误码

`LOCATION_NOT_FOUND`、`LOCATION_LOCKED`、`LOCATION_REQUIREMENT_MISSING`、
`DAO_ORIGIN_REQUIREMENT_MISSING`、`TRIBULATION_TERRACE_REQUIREMENT_MISSING`、
`ASCENSION_REQUIREMENT_MISSING`、`ENDING_STATE_REQUIRED`、`TRAVEL_BUSY`、
`PLAYER_OCCUPIED`、`TRAVEL_RESOURCE_INSUFFICIENT`、`TRAVEL_PASS_INSUFFICIENT`、
`TRAVEL_NOT_READY`、`TRAVEL_ROUTE_INVALID`、`OPERATION_CONFLICT`。

## 验收

入口不满足时不扣资源；普通通行物品只在创建时扣一次；飞升凭证创建时保留、抵达时原子扣除；
抵达凭证不足时位置不变且会话保持 `running`；重复移动/结算只回放，不重复扣费或消耗；
地点规则更新不改变已完成会话；未知地点不可进入资产写入流程。终局移动至少覆盖 QQ 官方和
OneBot V11 两条入口。
