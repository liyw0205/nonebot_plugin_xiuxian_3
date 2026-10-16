# 世界域：地点模型

`WorldLocation`：`location_key`、名称/别名、`world_key`、开放状态、共同入口条件、环境修正、允许动作、事件池、资源池和图鉴引用。
普通移动费用与方向准入属于区域的单条 `from -> to` 路线；地点级 `travel.anchor_min/max` 是当前未被玩法消费者读取的保留字段，
独立虚空航道仍由 `void_rules.ROUTES` 定义费用。

`PlayerLocation`：角色、当前位置、移动状态、到达时间、队伍 ID、最后结算 operation 和位置规则版本。

`TravelSession`：会话 ID、起点、终点、创建/预计/实际到达时间、费用快照、途中事件、状态和结果。
`snapshot_json` 以既有字段冻结来源/终点、已执行的费用、通行物及扣除时点，以及既有结算所需的领域状态；启程事务验证
共同门槛与路线门槛，成功会话代表本次准入已完成。此切片不扩展快照字段形状或写入内容版本，已开始行程不得依赖抵达时重新读取
当前地图或地点规则。

终局移动额外读取角色的 `endgame_status`：终局战胜利原子将发起者放到
`ascension.heaven_path` 并置为 `ascension_ready`，无需再次普通移动或扣飞升凭证；
`remained_in_world` 角色可从飞升路前往留界殿。普通移动在 `ascended`、`remained_in_world`
等冻结状态下拒绝写入。

地点开放条件由境界、任务、声望、道途、物品、时间窗口和前置事件组成。
