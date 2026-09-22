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
- `world.preview_travel` -> 查看地点准入、成本、来源和预计耗时，不写资产。
- `world.start_travel` -> 原子扣除移动成本、锁定凭证并创建移动会话。
- `world.settle_travel` -> 到达后写入位置；重复结算只回放首次结果。

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
均按整数公式计算，结算读取开始时的资质快照，重复 operation 只回放原结果。正式生产使用独立的 `production` application，不会绕过境界域
的修炼锁或 operation ledger。

聚气突破命令映射为 `突破预览 聚气`、`开始突破 聚气`、`结算突破` 和 `恢复虚弱`（可追加
`护脉` 或 `提前`）。开始突破独立使用 `progression.breakthrough_qi_gathering` operation，
结算独立使用 `progression.settle_breakthrough`；两者均保存规则版本、随机池、地点、道途、
资质、境界和成本快照。当前实现开放聚气与筑基目标；金丹及以上目标明确返回 `CONTENT_CLOSED`。
筑基突破固定使用 5 分钟会话、7,500 bp 基础成功率、聚气修为 70% 失败保留和 6 小时虚弱；
道基质量、功法、阵法辅修、筑基护脉丹和 +400 bp 失败保底均写入开始快照。

灵泉相关错误码包括 `LOCATION_REQUIRED`、`LOCATION_REQUIREMENT_MISSING` 和
`CULTIVATION_DAILY_LIMIT`；准入或次数不足时不扣体力、不创建修炼会话。

雾隐洞天移动命令映射为 `移动预览 雾隐洞天`、`前往 雾隐洞天`（或
`前往雾隐洞天`）和 `结算移动`。入口要求聚气 L4 以上、来源地点有效且持有
`item.cave_pass_basic`；开始时消耗 5 点体力、10 灵石和 1 张凭证，创建 2 分钟会话。
移动与修炼、生产、突破互斥；凭证、成本、来源和内容版本写入快照，重复 operation 不会
重复扣费或改写位置。
