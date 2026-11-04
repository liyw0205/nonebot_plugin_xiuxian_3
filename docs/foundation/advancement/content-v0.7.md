# v0.7 修炼与构筑养成内容基线：道脉重置

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，
`rule_version=advancement-0.7.0`。本版只把 `content-v0.1` 已登记、因重置成本与返还规则未冻结
而搁置的 `talent.reset_tree` 接入运行时；道途切换、道果、领域与战斗公式不变。

## 1. 规则 `talent.reset.standard`

| 字段 | 值 |
|:--|:--|
| 境界 | 筑基 L1 |
| 费用 | 灵石 300 |
| 返还 | 当前道途已修节点 `cost_points` 之和 × 100%（向下取整） |
| 冷却 | 604800 秒（7 天，自上次确认成功起） |
| 预览期限 | 900 秒（15 分钟） |
| 范围 | 只清空当前首要道途对应的道脉树 |

## 2. 玩家流程

`道脉重置预览` 校验入道、筑基 L1、当前树至少一个已修节点、无进行中的长动作、冷却已过，
生成 15 分钟冻结计划并列出节点、返还点数、费用与期限；不扣灵石、不删节点。
`确认道脉重置` 重新校验道途与节点集合未变，同事务扣 300 灵石、把节点完整快照写入
`talent_reset_records`、删除当前树节点、把返还点数加回 `talent_points` 并写一条正数
`talent_point_events`，计划置 `confirmed`，写 `talent.confirm_reset` operation。
`取消道脉重置` 只把最新待确认计划置 `cancelled`，不扣资产。

## 3. 失败与零写

未筑基 `TALENT_RESET_REQUIREMENT`；当前树无节点 `TALENT_RESET_EMPTY`；长动作
`TALENT_RESET_BUSY`；冷却未满 `TALENT_RESET_COOLDOWN`；无计划 `TALENT_RESET_NOT_FOUND`；
预览过期 `TALENT_RESET_PREVIEW_EXPIRED`；道途或节点集合变化 `TALENT_RESET_CONFLICT`；
灵石不足 `RESOURCE_INSUFFICIENT`；计划已确认/取消 `TALENT_RESET_STATE`；
同 operation 重放返回冻结结果。以上失败均不改变灵石、天赋点、节点或历史表。

## 4. 保留与影响

- 被清空节点的键、阶、消耗与解锁时间写入 `talent_reset_records`，不重新出现在 `我的道脉`。
- 其它道途的历史节点不动；道途转修后旧树仍保留，重置只作用于当前 `path_key` 对应树。
- 重置会降低当前道脉最高阶，可能使尚未选择的领域资格重新不足；已选领域不受影响。
- 不返还灵石或物品，不合并其它道途节点，不改节点效果、阶数、消耗或战斗公式。

## 5. 验收

`test_talent_reset.py` 覆盖内容合同与拒绝变体、空树、免费阶、返还精确值、节点删除与历史快照、
灵石不足、计划过期、节点变化冲突、同 operation 回放、冷却、重启、QQ 帮助；回归
`test_talent.py`、`test_path_switch.py`、`test_help.py`、`test_documentation.py`、
`test_content.py`、`test_m9_content_integrity.py` 与种子受影响组。
