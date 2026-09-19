# 境界域：公式与用例

## 用例

- `start_cultivation` -> 修炼会话和锁定资源。
- `settle_cultivation` -> 修为收益和资源流水。
- `advance_layer` -> 校验当前境内修为后晋升一层，不随机、不扣资源。
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

`CULTIVATION_BUSY`、`RESOURCE_INSUFFICIENT`、`BREAKTHROUGH_REQUIREMENT_MISSING`、`BREAKTHROUGH_BUSY`、`PROGRESSION_LOCKED`、`RULE_VERSION_UNAVAILABLE`。

同境晋层只允许 `current_layer + 1`，L10 后拒绝继续晋层；跨境突破只接受 L10
混元。修为不足不扣材料；突破重试返回同一结果；失败不同时多扣修为和材料；规则更新
不改变历史记录。