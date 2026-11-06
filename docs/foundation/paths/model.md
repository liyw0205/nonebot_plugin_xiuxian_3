# 道途域：数据模型

## PathBuild

`player_id`、`path_key`、`path_level`、`active_traits`、`state_payload`。

`path_key` 首版取：`body` 体修、`spell` 法修、`device` 器修、`demonic` 魔修、`beast` 妖修、`support` 辅修。

## SubProfession

`player_id`、`subprofession_key`、等级、熟练度、已学配方、每日精力上限和生产统计。配方内容不复制进玩家记录。

## PathContent 与 SubProfessionContent

运行时内容来自 `data/道途/道途.json` 的 `kind=path` 记录。每条记录提供稳定 `key`、显示用
`name`/`desc`、`status`、`aliases`、`active_skill` 和带 `item_key`/正整数 `quantity` 的
`entry_item_rewards`。只有 `support` 记录包含非空 `subprofessions`；辅修记录同样提供稳定键、名称、
别名和入门物品奖励。道途及同一路径内的辅修 key/name/alias 选择器必须唯一，技能与物品引用必须指向
开放内容，锁定记录不参与新入道。

公开的 `选择道途` 在同一 application 事务中解析稳定键、名称或别名，并在选择辅修时一并保存两个稳定键。
入道回执和资料展示按当前内容读取名称，玩家记录不保存展示文案。首阶段道途切换已接入：
`path_switch_plans` 保存预览计划与确认结果，`players.path_key`/`subprofession_key` 是唯一
生效状态，旧道脉/神通/装备作为历史保留并由各自消费者按当前路径过滤。独立 `select_subprofession`
仍未接入，道途切换不改变战斗引擎或道途战斗效果。

## SwitchPlan

保存旧道途、新道途、保留项、冻结项、转化项、清理项、费用、有效期、确认状态和 operation ID。

首阶段实现使用 `path_switch_plans`：`plan_id`、`player_id`、预览/确认 operation、旧/新道途、
目标辅修、`pending/confirmed/cancelled/expired` 状态、费用与快照 JSON、过期时间与确认时间。
切换次数与最近切换时间由该表历史推导，不另加 `players` 列。

元婴重构使用 `path_rebuild_plans` 保存 24 小时预览与确认结果，使用 `path_rebuilds` 保存每名角色
唯一的一次性记录（旧/新道途、旧等级、继承等级、旧树节点快照）。继承等级不新增 `players` 列，
由 `path_rebuilds.inherited_level` 与目标树 `talent_node_states` 的 `learned` 节点共同表达；
旧树节点不删除，作为冻结历史保留。
