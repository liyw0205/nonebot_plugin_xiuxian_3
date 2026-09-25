# 世界域：用例与验收

## 用例

- `get_location(player_id)` -> 当前地点和可用动作。
- `preview_travel(player_id, destination)` -> 条件、费用、时间，不写资产。
- `start_travel(player_id, destination, operation_id)` -> 移动会话。
- `settle_travel(player_id, operation_id)` -> 新位置和途中事件；服务端从该角色唯一的运行中会话读取路线快照。
- `demon.abyss_market` -> 元婴 L1、魔界声望 `>=200`，5 分钟/12 体力/500 灵石；声望不足返回 `FACTION_REPUTATION_INSUFFICIENT`，成功会话冻结准入和 `content-0.3`/`world-0.3.0` 版本。
- `board_cloud_boat(player_id, route_key, operation_id)` -> v0.2 云舟会话，冻结路线、费用和凭证。
- `settle_cloud_boat(player_id, operation_id)` -> 按冻结快照抵达洞天二层、深渊门或返回云城。
- `accept_demon_intro(player_id, operation_id)` -> 在深渊门确认风险，写入一次性入口资格和魔界声望，不发魔界资源。
- `use_array_hall(player_id, operation_id)` -> 再次校验宗门/教学邀请，只确认阵堂权限，不自动创建生产订单；生产域的阵堂配方在预览和开始时复用同一校验。
- `leave_closed_location(player_id, operation_id)` -> 撤离结果。

## 错误码

`LOCATION_NOT_FOUND`、`LOCATION_LOCKED`、`LOCATION_REQUIREMENT_MISSING`、
`DAO_ORIGIN_REQUIREMENT_MISSING`、`TRIBULATION_TERRACE_REQUIREMENT_MISSING`、
`ASCENSION_REQUIREMENT_MISSING`、`ENDING_STATE_REQUIRED`、`TRAVEL_BUSY`、
`PLAYER_OCCUPIED`、`TRAVEL_RESOURCE_INSUFFICIENT`、`TRAVEL_PASS_INSUFFICIENT`、
`TRAVEL_NOT_READY`、`TRAVEL_ROUTE_INVALID`、`OPERATION_CONFLICT`。
跨界声望门槛另有 `FACTION_REPUTATION_INSUFFICIENT`。
v0.2 另有 `CLOUD_ROUTE_LOCKED`、`CLOUD_FARE_INSUFFICIENT`、`ADVANCED_CAVE_PASS_MISSING`、
`ARRAY_HALL_PERMISSION_DENIED`、`DEMON_INTRO_REQUIREMENT_MISSING`。

## 验收

入口不满足时不扣资源；普通通行物品只在创建时扣一次；飞升凭证由终局战托管，成功/留界分支
消耗，失败/取消/大厅超时返还；重复移动/结算只回放，不重复扣费或消耗；
地点规则更新不改变已完成会话；未知地点不可进入资产写入流程。终局移动至少覆盖 QQ 官方和
OneBot V11 两条入口。
