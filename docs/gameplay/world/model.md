# 世界域：地点模型

`WorldLocation`：`location_key`、`world_key`、`parent_key`、入口条件、移动费用、环境修正、允许动作、事件池、资源池和内容版本。

`PlayerLocation`：角色、当前位置、移动状态、到达时间、队伍 ID、最后结算 operation 和位置规则版本。

`TravelSession`：会话 ID、起点、终点、创建/预计/实际到达时间、费用快照、途中事件、状态和结果。
`snapshot_json` 必须冻结来源、终点、内容/规则版本、资源成本、通行物品和
`consume_pass_on_arrival`；终局凭证不能依赖抵达时重新读取当前地点规则。

终局移动额外读取角色的 `endgame_status`：`ascension_ready` 只允许从天劫台前往飞升路，
`remained_in_world` 只允许从飞升路前往留界殿。普通移动在 `ascended`、`remained_in_world`
等冻结状态下拒绝写入。

地点开放条件由境界、任务、声望、道途、物品、时间窗口和前置事件组成。
