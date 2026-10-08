# 道途域：用例与验收

## 用例

- `select_path(player_id, path_key_or_name_or_alias, subprofession_key_or_name_or_alias, operation_id)` ->
  稳定道途/辅修键、当前内容名称和入门所得；辅修在入道事务中一并选择。
- `preview_path_switch(player_id, new_path_key)` -> `SwitchPlan`，只读。
- `confirm_path_switch(plan_id, operation_id)` -> 新道途和状态快照。
- 独立 `select_subprofession` 尚未接入；生产辅修记录仍由既有生产用例维护，不在本切片新增入口。
- `settle_subprofession_action(order_id, operation_id)` -> 熟练度和生产结果。

## 错误码

`PATH_NOT_FOUND`、`PATH_ALREADY_SELECTED`、`PATH_LOCKED`、`PATH_REQUIREMENT_MISSING`、`PATH_SWITCH_COOLDOWN`、`PATH_STATE_CONFLICT`、`SUBPROFESSION_NOT_FOUND`、`PROFICIENCY_LIMIT_REACHED`。

## 验收

- 只能有一个首要道途。
- 选择失败不激活被动、不扣资源。
- 锁定、歧义、缺字段和坏奖励引用在任何写入前拒绝；两个适配器共用同一 application。
- 成功 operation 可在重启后按稳定键结果回放且不重复奖励；内容改名后的旧文字输入明确拒绝，不保留兼容分支。
- 切换计划确认前不改变角色。
- 魔修动作记录侵蚀来源。
- 辅修熟练度只在生产成功结算后增加一次。
