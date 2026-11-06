# v0.12 守界路线战事加成

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.12`，
`rule_version=social-0.12.0`。本版把 `content-v0.8.md` 记录在案的后续项接上：魔界入侵结算读取玩家
宗门的 `dao_route_state`，守界路线按既有 `defense_event_bonus_bp` 提高战场贡献。本版不改任何
`data/` 文件，也不新增内容键或命令。

## 1. 内容与数值

`data/社交/道统路线.json` 的 `route.dao_settlement.guard_world` 已带
`bonus.defense_event_bonus_bp=1000`（与 v0.8 冻结值一致，上限 3000 bp 由加载器校验）。
贡献来源与每份折算值仍来自 `data/事件/事件.json` 的 `event.demon_invasion`：

| 来源 | `action` | 折算 | 守界路线实际入账 |
|:--|:--|--:|--:|
| 已结算战斗 | `战斗` | 每 100 伤害 1 点 | `基础 × 1.10`（向下取整） |
| 已结算运输 | `运输` | 每份 10 点 | 10 → 11 |
| 已缴费维护 | `维修` | 每份 15 点 | 15 → 16（16.5 向下取整） |

实际入账 = `基础贡献 * (10000 + defense_event_bonus_bp) // 10000`。数值只从路线内容读取，
事件代码不复制 1000；路线内容缺失、加成键不匹配或数值非法时按 0 bp 处理，不阻断结算。
不设贡献上限，加成随每次来源入账即时生效。

## 2. 记录流程

`贡献魔界战场` 在来源核验与去重通过后：

1. 读取玩家当前活跃宗门与 `dao_route_state.route_key`；
2. 仅当路线为 `route.dao_settlement.guard_world` 时读取该路线的 `defense_event_bonus_bp`；
3. 按上式折算本次入账，写入 `world_event_contribution_events.quantity`（基础）与
   `applied_quantity`（实际），并以实际值累加 `world_event_contributions`；
4. 结果与 `operations` 载荷新增 `base_contribution`、`route_bonus_bp`、`applied_contribution`；
5. 个人贡献、全服贡献与 `success` 判定均使用加成后的实际值；领取门槛 `min_contribution=50`
   同样按实际值判断。

加成在每次贡献入账时按当时路线计算，不在轮次创建或领取时回算。路线在轮次中途变更时，
已入账部分保持不变，后续来源按新路线计算，`route_bonus_bp` 保留每次实际使用的 bp 供审计。

## 3. 呈现与兼容

`贡献魔界战场` 回执在有加成时新增一行，例如
`- **本次入账**：10 + 守界路线 10% = 11`；无加成（无宗门、无路线、非守界路线或加成非法）时
不显示该行，回执与旧版一致。百分比由 bp 换算，不在文案里另写常量。不新增命令、按钮或帮助段；
`修仙帮助 社交` 的既有路线段不变。

- 结果新增字段只进入 `operations` 与贡献回执载荷，事件轮次快照结构不变。
- 旧 operation 结果缺 `base_contribution` / `route_bonus_bp` / `applied_contribution` 时
  按 0 回放，不改写已落账的贡献。
- 相同 operation 回放返回首次结果，不重复折算或重复累加；重启后结果与累计贡献保持。
- 来源去重仍以 `(round_id, player_id, source_operation_id)` 唯一约束为准，加成不改变去重语义。
- 不改变轮次时间窗、目标数量、嘉奖内容、世界功勋、阵营声望或事件错误码。

## 4. 错误与边界

不新增错误码。无活跃宗门、宗门无 `dao_route_state`、路线非守界、路线内容缺失或
`bonus.value_bp` 非法时均按 0 bp 入账。若未来路线内容被移除，已入账贡献不回算。

## 5. 验收

`test/test_demon_invasion_guard_route.py` 覆盖：

- 守界路线运输来源：`base_contribution=10`、`route_bonus_bp=1000`、
  `applied_contribution=11`、累计 11，回执含 `10 + 守界路线 10% = 11`，
  事件表 `quantity=10` 与 `applied_quantity=11`；
- 五次运输累计 55，达到领取门槛后正常结算与领奖，嘉奖不变；
- 相同 operation 回放与进程重启：字段与累计贡献都不重复累计；
- 无宗门、宗门无路线、飞升路线、留界路线：0 bp、入账 10、回执无加成段；
- 旧贡献载荷缺新字段：按 0 回放，`applied_quantity` 保持 11。

回归：`test_demon_event.py`、`test_tribulation_endgame_chain.py`（路线读取共用语义）、
`test_dao_route.py`、`test_events.py`、`test_documentation.py`。
