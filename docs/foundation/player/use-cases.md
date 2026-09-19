# 角色域：用例与验收

## 用例

- `create_player(platform, platform_user_id, scene, operation_id)` -> `player_id`、`stage=new_user`。
- `start_seeking(player_id, root_affinity, operation_id)` -> 资质快照、新手资源和 `stage=mortal`。
- `swap_qualification_stats(player_id, left_key, right_key, operation_id)` -> 一次属性交换后的快照引用。
- `complete_intro(player_id, guide_key, operation_id)` -> 当前引导进度；三项均完成才进入 `seeker`。
- `enter_cultivation(player_id, path_key, subprofession_key, operation_id)` -> 道途、可选主辅修和 `stage=cultivator`。
- `rename_player(player_id, new_name, operation_id)` -> 名称和冷却。
- `get_profile(player_id)` -> 只读状态 DTO。

## 错误码

`PLAYER_NOT_FOUND`、`PLAYER_ALREADY_EXISTS`、`PLAYER_STAGE_CONFLICT`、`PLAYER_SUSPENDED`、`SEEKING_ALREADY_DONE`、`NAME_INVALID`、`NAME_TAKEN`、`OPERATION_CONFLICT`。

## 验收

- 重复创建返回同一角色，不产生第二行、钱包或资质。
- 寻仙重试返回同一快照和同一奖励结果，不重新随机或发奖。
- 资质总和恒为 60，单项 5–15，且只允许一次交换。
- 未完成三项凡人引导时，选择道途拒绝且无资产变化。
- `support` 未提供有效主辅修时入道拒绝，不发放入道奖励。
- 暂停角色可读不可写；改名失败不写名称历史。

稳定内容键、数值、奖励与完整失败语义见 [v0.1 内容基线](content-v0.1.md)。