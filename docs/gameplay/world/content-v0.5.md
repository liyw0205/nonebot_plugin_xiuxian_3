# v0.5 世界地点内容基线：虚空航道

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=world-0.5.0`。虚空地点通常要求炼虚；炼虚许可来源的档案航道允许已完成三次界壁试炼的化神角色进入。进入依赖 `item.void_anchor` 和 stats v0.5 的抗性/不稳定规则。

| `location_key` | 准入 | 航行/成本 | 动作与限制 |
|:--|:--|:--|:--|
| `void.first_route` | 炼虚、虚空锚 >=1 | 30 分钟 / 按抗性计算 1–3 锚、35 体力 | 虚空遗迹、节点采集、风暴事件 |
| `void.archive_ruins` | 化神且已完成界壁试炼 3 次，或炼虚；虚空锚 >=2 | 45 分钟 / 2–4 锚、40 体力 | 档案守卫、规则碎片、`quest.break_void` 物品 |
| `void.sect_fortress` | 宗门等级 >=5、炼虚或受邀 | 30 分钟 / 1–3 锚、20 体力 | 跨服宗门战、堡垒委托 |
| `cave.time_garden` | 炼虚、完成虚实试炼 | 30 分钟 / 30 体力、`item.void_crystal` 1 | 时间生产加速，单订单一次 |
| `void.void_market` | 炼虚、虚空声望 >=1000 | 30 分钟 / 1–3 锚、10 体力 | 虚空材料固定价交易 |

虚空集市库存 `market.void.week.<week_id>` 于服务器周一 00:00 创建，20 个限量槽；购买操作锁库存与买方锚/灵石，支付成功才减少库存，失败释放锁。库存不随客户端时区变化。

航行会话开始时冻结路线、成本、抗性、`void_instability`、事件池和队伍；15% 风暴概率由 `void.route.<route>.v0.5` 保存 roll。风暴失败损失额外 1 锚（若有）并设不稳定；不会把锚扣成负数。航道会话不可普通取消，超时由恢复任务按快照抵达或受控返回最近安全门户。

错误：`VOID_ROUTE_LOCKED`、`VOID_ANCHOR_INSUFFICIENT`、`VOID_REPUTATION_INSUFFICIENT`、`VOID_MARKET_SOLD_OUT`、`VOID_TRAVEL_BUSY`。关闭后停止新航行/集市购买，旧航行按快照结算、旧库存冻结只读。验收：抗性成本最少 1 锚；风暴重试不重抽；库存并发不超卖；时序福地不叠加多次同订单；不稳定只影响虚空航行。
