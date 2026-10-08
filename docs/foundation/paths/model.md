# 道途域：数据模型

## PathBuild

`player_id`、`path_key`、`path_level`、`active_traits`、`state_payload`、`switch_count`、`last_switch_at`。

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
入道回执和资料展示按当前内容读取名称，玩家记录不保存展示文案。当前未接入独立的辅修选择或道途切换用例，
也不在本切片改变道途战斗效果。

## SwitchPlan

保存旧道途、新道途、保留项、冻结项、转化项、清理项、费用、有效期、确认状态和 operation ID。
