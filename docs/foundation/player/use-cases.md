# 角色域：用例与验收

## 用例

- `create_player(platform, platform_user_id, scene, dao_name?, operation_id)` -> `player_id`、`dao_name`、`stage=new_user`。
- `start_seeking(player_id, root_affinity, operation_id)` -> 资质快照、新手资源和 `stage=mortal`。
- `swap_qualification_stats(player_id, left_key, right_key, operation_id)` -> 一次属性交换后的快照引用。
- `complete_intro(player_id, guide_key, service_key?, operation_id)` -> 当前引导进度；三项均完成才进入 `seeker`。采集需位于近郊，生产教学需选择炼丹、炼器或布阵。
- `travel_intro(player_id, destination, operation_id)` -> 新手城与近郊之间的教学移动；成功扣除固定体力。
- `enter_cultivation(player_id, path_key, subprofession_key, operation_id)` -> 道途、可选主辅修和 `stage=cultivator`。
- `rename_player(player_id, dao_name, operation_id)` -> 道号和改名状态。
- `get_profile(player_id)` -> 只读状态 DTO。

## 错误码

`PLAYER_NOT_FOUND`、`PLAYER_ALREADY_EXISTS`、`PLAYER_STAGE_CONFLICT`、`PLAYER_SUSPENDED`、`SEEKING_ALREADY_DONE`、`INVALID_DAO_NAME`、`DAO_NAME_TAKEN`、`RENAME_CARD_REQUIRED`、`INVALID_GUIDE`、`INVALID_DESTINATION`、`LOCATION_REQUIRED`、`RESOURCE_INSUFFICIENT`、`INVALID_PATH`、`SUBPROFESSION_REQUIRED`、`PATH_ALREADY_SELECTED`、`OPERATION_CONFLICT`。

## 验收

- 重复创建返回同一角色，不产生第二行、钱包或资质。
- 寻仙重试返回同一快照和同一奖励结果，不重新随机或发奖。
- 资质总和恒为 60，单项 5–15，且只允许一次交换。
- 未完成三项凡人引导时，选择道途拒绝且无资产变化。
- `support` 未提供有效主辅修时入道拒绝，不发放入道奖励。
- 暂停角色可读不可写；改名失败不写名称历史。
- `开始修仙 <道号>` 校验长度和全局唯一性；不填写时保持未命名。
- 未命名角色第一次使用 `修仙改名 <道号>` 不消耗改名卡；已有道号再次修改必须拥有改名卡。
- 教学采集离开新手城前往近郊，采集和移动的体力扣除与 operation 回放一致；返回新手城不会重置已完成引导。

稳定内容键、数值、奖励与完整失败语义见[完整内容开发总表](../../content-development.md)；`content-v0.1.md` 仅用于复原 `content-0.1` 快照。
