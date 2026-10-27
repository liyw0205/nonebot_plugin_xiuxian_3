# v0.7 道历与运营循环内容基线（时序行卷）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，`rule_version=routine-0.7.0`。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 时序行卷 | `pass.timetrace`：开放卷，无境界门槛 | 21 日、24 级、每级 60 点（总 1440）；日上限 120、周上限 500；开卷冻结快照 |
| 来源 | 采集、派遣与生产三类已结算 operation | `exploration.settle` 20、`livelihood.harvest` 25、`production.complete` 25、`specials.settle_dispatch` 30、`time_fort.settle` 40 |
| 免费线 | 时痕草 + 既有材料 + 地方名望 | 24 档；物品仅 `item.herb.*`/`item.mat.*`/`item.ore.*` 普通材料，名望记 `local.dao_service`（上限 1000） |
| 付费线 | 需当前有效 `dao_contract.monthly` | 24 档；时痕草、阵砂、`item.clue.recipe_basic`、`item.token.spirit_tree_water` |
| 选卷 | `开始行卷 [卷名]` / `问道行卷 [卷名]` | 缺省问道卷；`时序`/`时序行卷`/`timetrace`/`pass.timetrace` 选时序卷 |
| 并发 | 同一角色同时仅一卷在途 | 上一卷周期未结束时开另一卷返回 `WAYFARING_ALREADY_STARTED` |

## 合同

- 卷键必须属于已登记卷集合（`pass.wayfaring`、`pass.timetrace`）；快照身份按数据库行的卷键校验，
  恢复快照不读取现行内容，未知卷键整卷拒绝。
- 来源集合按卷精确匹配：多一条、少一条、卷键不符、布尔或非正点数都拒绝加载；问道卷的八种来源
  不因时序卷存在而放宽，时序卷也不能接受问道卷的专属来源。
- 免费线物品必须是 `crafting_material` 效果的普通材料；付费线物品白名单按卷固定，时序卷允许
  时痕草、阵砂与既有配方线索/灵木水分券，问道卷维持原白名单。
- 奖励引用必须闭合：物品存在且为 active，材料在 `gathering_sources` 中声明来源；时痕草由
  `explore.time_garden` → `reward_pool.exploration.time_garden` 产出，未声明来源的材料不得发奖。
- 点数事件按来源 operation 唯一绑定，同时受日、周及周期总量封顶；非本卷来源（如道历问安之于
  时序卷）不计分，触顶来源仍记录为已处理并标记 `capped`。
- 领取幂等：原 operation 回放冻结结果，不重复发奖；换卷后旧卷仍可查询，已领集合与点数事件按
  `pass_id` 隔离。
- 内容关闭只阻止新开卷；已开周期按快照继续计分与领奖，周期结束后不得新领奖。

## 边界

不新增命令、数据库表、物品、地点、称号或配方；问道卷数值、来源、奖励与付费白名单不变。
时序卷的奖励全部来自既有材料与既有凭证/线索物品，不引入新的产出渠道。
