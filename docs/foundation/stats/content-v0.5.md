# v0.5 属性内容基线：炼虚虚力与空间抗性

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=stats-0.5.0`。

炼虚突破成功时增加气血 +1,500、灵力 +1,200、负重 +100；初始化 `void_power=200/200`、`space_resistance_bp=1500`、虚空锚背包上限 20。增量和初始资源只由突破 operation 应用一次。

| 键 | 上限/恢复 | 获得 | 消耗与公式 |
|:--|:--|:--|:--|
| `void_power` | 0–200；业务日恢复至 200 | 炼虚突破、虚空事件 | 技能 20–60；不足拒绝，不借贷 |
| `item.void_anchor` | 背包最多 20 | 虚空节点、炼虚奖励 | 航道移动 1–3；不足不建会话 |
| `space_resistance_bp` | 硬上限 7500 bp | 基础 1500、装备、道途、领域 | 减少风暴损失与航行成本 |
| `void_instability` | 48 小时 | 炼虚突破失败 | 航行最终成本 ×13000 bp，禁用虚空技能 |

航行成本：`max(1, ceil(route_anchor_cost * (20000-space_resistance_bp) / 20000))`；若 `void_instability` 生效再乘 13000 bp 并向上取整。抗性最多将基础成本减半，不能降为 0。虚空风暴损失按内容池结算：`loss_bp=max(500, base_loss_bp-space_resistance_bp//2)`；损失对象和池版本保存于会话。

`VoidSnapshot` 保存虚力、锚、抗性、不稳定状态、航道、地点、装备、道途、版本和随机结果。错误：`VOID_POWER_INSUFFICIENT`、`VOID_ANCHOR_INSUFFICIENT`、`SPACE_RESISTANCE_CAP`、`VOID_INSTABILITY_ACTIVE`。关闭后不建新航道，已开始会话按快照结算。验收：每日恢复不溢出/不双加；成本至少 1 锚；不稳定只影响虚空；风暴重试不重抽；抗性来源可解释。