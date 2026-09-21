# v0.5 探索内容基线：虚空航道、档案与时序福地

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=exploration-0.5.0`。开始时保存虚空锚、抗性、不稳定、航道、队伍、生产订单引用和随机池。

| `mode_key` | 前置 | 时长/成本 | 保底/随机 | 失败与上限 |
|:--|:--|:--|:--|:--|
| `explore.void_route` | 第一航道、炼虚 | 30 分钟 / 35 体力、航行锚成本 | 虚空晶 1、`loot.void.ruins.v0.5` | 风暴 15%；每天 3 |
| `explore.archive_ruins` | 档案遗迹、声望 500 | 45 分钟 / 40 体力、2 锚 | `item.void_archive` 1、规则碎片 | 守卫战 40%；每天 2 |
| `explore.time_garden` | 时序福地、虚实试炼 | 30 分钟 / 30 体力、虚空晶 1 | 生产加速券 1、时间花 1 | 仅绑定一个 running 生产订单；每天 2 |

`event.void_storm` roll 命中后按 stats v0.5 抗性计算额外锚损失；锚不足时损失为现有全部锚、设 `void_instability`，但不让背包负数。风暴不取消已经获得的保底虚空晶。档案遗迹的 `item.void_archive` 每周最多 1 个，超过时转为虚空晶 3；转换写入奖励快照。

时序福地只能绑定 `production_order_id`，把该订单剩余时间减少 3000 bp，最低保留 1 分钟；同一订单/版本最多一次，取消或失败订单不返还加速券。错误：`VOID_ORDER_ALREADY_ACCELERATED`、`VOID_ARCHIVE_WEEKLY_CAP`、`VOID_ANCHOR_INSUFFICIENT`、`VOID_INSTABILITY_ACTIVE`。关闭后旧航道/订单按快照完成。验收：风暴重试不重复扣锚；加速不叠加；档案周上限转换稳定；不稳定只影响虚空会话。