# 道途域：用例与验收

## 用例

- `select_path(player_id, path_key, operation_id)` -> 道途和初始被动。
- `preview_path_switch(player_id, new_path_key)` -> `SwitchPlan`，只读。
- `confirm_path_switch(plan_id, operation_id)` -> 新道途和状态快照。
- `select_subprofession(player_id, key, operation_id)` -> 辅修记录。
- `settle_subprofession_action(order_id, operation_id)` -> 熟练度和生产结果。

## 错误码

`PATH_NOT_FOUND`、`PATH_ALREADY_SELECTED`、`PATH_LOCKED`、`PATH_REQUIREMENT_MISSING`、`PATH_SWITCH_COOLDOWN`、`PATH_STATE_CONFLICT`、`SUBPROFESSION_NOT_FOUND`、`PROFICIENCY_LIMIT_REACHED`。

## 验收

- 只能有一个首要道途。
- 选择失败不激活被动、不扣资源。
- 切换计划确认前不改变角色。
- 魔修动作记录侵蚀来源。
- 辅修熟练度只在生产成功结算后增加一次。