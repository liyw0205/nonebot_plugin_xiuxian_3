# 道途域：数据模型

## PathBuild

`player_id`、`path_key`、`path_level`、`active_traits`、`state_payload`、`switch_count`、`last_switch_at`、`rule_version`。

`path_key` 首版取：`body` 体修、`spell` 法修、`device` 器修、`demonic` 魔修、`beast` 妖修、`support` 辅修。

## SubProfession

`player_id`、`subprofession_key`、等级、熟练度、已学配方、每日精力上限、生产统计和规则版本。配方内容不复制进玩家记录。

## SwitchPlan

保存旧道途、新道途、保留项、冻结项、转化项、清理项、费用、有效期、确认状态和 operation ID。