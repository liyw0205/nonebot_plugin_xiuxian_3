# v0.2 属性内容基线：金丹资源、阵营与耐久

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.2`
- `rule_version`：`stats-0.2.0`
- 新资源只在金丹内容准入后创建；v0.1 读取时为 0 或 `locked`，不得提前发放。

## 1. 金丹成长与资源表

金丹突破成功时一次性应用基础成长：`body/spirit/insight/root/agility` 各 +3；`fortune` 不自动增加。成长写在金丹突破 operation，不能因查询或重连重复应用。

| `resource_key` | 初始/上限 | 获得来源 | 消耗/状态 | 禁止用途 |
|:--|:--|:--|:--|:--|
| `merit` | 0 / 无硬上限 | 宗门建设、金丹事件、阵营任务 | 宗门服务、金丹内容许可 | 不能兑换灵石 |
| `faction_reputation.<realm>` | 0 / 10,000 | 该界任务、贸易、事件 | 地点/任务/盟约准入 | 三界不可互换 |
| `artifact_durability` | 实例 0–10000 bp | 装备创建/维修 | 器修技能、生产、战斗损耗 | 耐久 0 的法器不能主动使用 |
| `pollution` | 0 / 100 | 魔界行动、魔修技能、契约 | 心魔、敌对、净化 | 不能用灵石直接归零 |

`pollution` 80–99 为 `tainted`：魔界收益 +500 bp、玄天界声望任务奖励 -2000 bp；100 为 `corrupted`：拒绝阵营声望领取和高风险探索，必须结算净化/心魔会话。任何阈值变化写状态流水。

## 2. 金丹公式与上限

```text
max_hp_golden_core = max_hp_previous + 300
max_mp_golden_core = max_mp_previous + 240
faction_damage_bp = min(faction_reputation.current, 3000)
artifact_effect_bp = floor(durability_bp * item_effect_bp / 10000)
```

阵营声望只在对应世界/事件标签下提供 `faction_damage_bp`，不能在所有战斗叠加。装备耐久的效果按比例衰减；`durability_bp=0` 时效果为 0，实例仍保留且可维修。金丹常驻增伤上限为 4,500 bp、临时总上限 10,000 bp；闪避与控制抵抗仍硬上限 8,500 bp。

## 3. 耐久与污染结算

- 普通金丹战斗：参与的可损耗法器每场 -100 bp；器修主动机关额外 -150 bp。
- 高风险洞天/精英战：按内容表覆盖，默认每场 -250 bp。
- 维修：`production.repair_artifact` 消耗对应材料与精力；恢复量和费用按物品内容定义，重复 operation 不重复恢复。
- 净化：`production.purify_pollution` 或 `event.resolve_heart_demon`；v0.2 默认每次最多降低 20，不能低于 0。

资源不足、实例不存在、实例绑定于进行中战斗/订单、耐久已满、污染状态冲突均不产生部分写入。维修/净化使用独立 operation，不能与战斗奖励合并。

## 4. 关闭与验收

关闭 v0.2 后停止新阵营/耐久/污染写入口；已有装备耐久、污染和声望仅可读，或由原版本会话结算。回滚先冻结金丹经济写入，再比对每个实例耐久与操作流水。

验收：金丹成长只应用一次；三界声望不互换；非对应地点没有阵营伤害；耐久归零不能使用装备但可维修；污染阈值进出只触发一次；金丹上限截断记录来源；所有资源变化可由 operation 重放。