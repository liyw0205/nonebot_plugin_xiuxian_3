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

当前已实现的命令映射为 `开始修炼`、`结算修炼`、`恢复修炼`、`取消修炼`、`晋升境界` 和 `恢复状态`。
感气调息会话固定消耗 2 点体力、持续 10 分钟、基础修为 40；悟性按整数公式影响收益。
结算读取开始时的资质快照，重复 operation 只回放原结果。聚气、筑基突破和正式生产尚未
接入本运行时。
