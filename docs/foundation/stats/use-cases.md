# 属性域：公式、错误与验收

## 公式

```text
layer_tail = max(realm_layer - 1, 0)
max_hp = hp_base + rank_growth * realm_rank + layer_growth * layer_tail + body_factor * body + root_factor * root + permanent_hp
max_mp = mp_base + rank_growth * realm_rank + layer_growth * layer_tail + spirit_factor * spirit + insight_factor * insight + permanent_mp
initiative = initiative_base + agility_factor * agility + permanent_initiative
attack = attack_base + body // attack_body_divisor
```

气血与灵力各自的境界系数、其他基础公式、武器淬炼系数和比例上限均由
`data/养成/规则.json`的`stats.formula`提供。上述基础与永久值再按计算生命周期叠加构筑。
代码使用定点整数，不使用二进制浮点作为权威结果；不在战斗域保留第二套数值表。

## 用例

`preview_stats`、`freeze_stats(player_id, purpose, operation_id)`、`explain_stat(snapshot_id, stat_key)`。

## 错误码

`STAT_PLAYER_NOT_FOUND`、`STAT_RULE_NOT_FOUND`、`STAT_SOURCE_MISSING`、`STAT_VALUE_OUT_OF_RANGE`、`STAT_SNAPSHOT_INVALID`、`NUMERIC_INVARIANT_VIOLATION`。

## 验收

相同输入生成相同摘要；装备变化生成新快照；来源可解释；软上限返回截断原因；规则更新不改变历史快照。

专项验收须覆盖：永久气血与灵力只加一次；装备词条、淬炼和耐久一致；功法与体质同乘区
相加，反伤不重复；面板与普通PvE、队伍、竞技及观战的开始值同源；探索及远古洞天、虚空遗迹、
时序堡垒的延迟遭遇不重读当前构筑；坏JSON、重复字段、缺字段、布尔值、小数和未知效果拒绝且事务无部分写入；
历史operation在重启、内容变化后仍原样重放。两适配器调用共享应用和仓储，不能维护各自属性公式。
