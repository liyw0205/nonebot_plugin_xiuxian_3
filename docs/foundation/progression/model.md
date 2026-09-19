# 境界域：数据模型

## Progression

`player_id`、`realm_key`、`realm_layer`（凡人 0，正式境界 1–10）、`realm_cultivation`、
`total_cultivation`、`foundation_quality`、`breakthrough_state`、`pity_count`、
`debuff_until`、`rule_version`。显示段位不持久化：L1–3 入门、L4–6 稳固、L7–9 圆满、L10 混元。

旧 `realm_stage`/`cultivation_exp` 只允许存在于显式迁移输入；新模型与新迁移不创建这些字段。

## CultivationSession

`session_id`、`player_id`、行动类型、地点、开始/结束时间、消耗快照、收益快照、状态和 operation ID。

## BreakthroughRecord

保存目标境界、输入 StatSnapshot、材料、成功率、随机结果、成功/失败、损失、状态变化和公式版本。记录不可变。