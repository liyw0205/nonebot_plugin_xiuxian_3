# 属性域：公式、错误与验收

## 公式

```text
max_hp = 100 + 20 * realm_index + 8 * body + 5 * root
max_mp = 60 + 18 * realm_index + 10 * spirit + 4 * insight
physical_damage = skill_base * (1 + body / 100) * path_factor
spell_damage = skill_base * (1 + spirit / 100) * path_factor
```

代码使用定点整数，不使用二进制浮点作为权威结果。

## 用例

`preview_stats`、`freeze_stats(player_id, purpose, operation_id)`、`explain_stat(snapshot_id, stat_key)`。

## 错误码

`STAT_PLAYER_NOT_FOUND`、`STAT_RULE_NOT_FOUND`、`STAT_SOURCE_MISSING`、`STAT_VALUE_OUT_OF_RANGE`、`STAT_SNAPSHOT_INVALID`、`NUMERIC_INVARIANT_VIOLATION`。

## 验收

相同输入生成相同摘要；装备变化生成新快照；来源可解释；软上限返回截断原因；规则更新不改变历史快照。