# 境界域：公式与用例

## 用例

- `start_cultivation` -> 修炼会话和锁定资源。
- `settle_cultivation` -> 修为收益和资源流水。
- `recover_cultivation` -> 超过 24 小时普通窗口后，按原始快照完成一次迟到结算。
- `cancel_cultivation` -> 取消尚未结算的修炼并返还已锁定体力。
- `advance_layer` -> 校验当前境内修为后晋升一层，不随机、不扣资源。
- `recover_resources` -> 按 30 分钟周期恢复体力/精力并封顶。
- `preview_breakthrough` -> 条件、成功率、预计损失，不写资产。
- `start_breakthrough` -> 突破记录、快照和锁定材料。
- `settle_breakthrough` -> 新境界或失败状态。

## 公式

```text
success_bp = clamp(base_bp + preparation_bp + foundation_bp + support_bp - risk_bp,
                   minimum_bp, maximum_bp)
```

运行时使用万分比整数。

## 错误码与验收

`CULTIVATION_BUSY`、`CULTIVATION_NOT_READY`、`CULTIVATION_NOT_FOUND`、`RESOURCE_INSUFFICIENT`、`REALM_CULTIVATION_INSUFFICIENT`、`REALM_LAYER_INVALID`、`BREAKTHROUGH_REQUIREMENT_MISSING`、`BREAKTHROUGH_BUSY`、`PROGRESSION_LOCKED`、`RULE_VERSION_UNAVAILABLE`。

同境晋层只允许 `current_layer + 1`，L10 后拒绝继续晋层；跨境突破只接受 L10
混元。修为不足不扣材料；突破重试返回同一结果；失败不同时多扣修为和材料；规则更新
不改变历史记录。

当前已实现的命令映射为 `开始修炼`、`开始修炼 灵泉`、`结算修炼`、`恢复修炼`、
`取消修炼`、`晋升境界` 和 `恢复状态`。调息会话固定消耗 2 点体力、持续 10 分钟、
基础修为 40；灵泉会话要求感气二层、完成教学采集并位于灵泉谷，固定消耗 3 点体力、
持续 15 分钟、基础修为 70，使用 11500 bp 环境倍率且每日最多 4 次。灵泉会话使用
`progression-0.1.2` 规则版本，调息继续使用 `progression-0.1.1`。悟性、环境和状态倍率
均按整数公式计算，结算读取开始时的资质快照，重复 operation 只回放原结果。聚气、筑基
突破尚未接入本运行时；正式生产使用独立的 `production` application，不会绕过境界域
的修炼锁或 operation ledger。

灵泉相关错误码包括 `LOCATION_REQUIRED`、`LOCATION_REQUIREMENT_MISSING` 和
`CULTIVATION_DAILY_LIMIT`；准入或次数不足时不扣体力、不创建修炼会话。
