# v0.1 交易与经济内容基线：钱包、固定摆摊与生产委托

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.1`，`rule_version=economy-0.1.0`。首版唯一货币为 `currency.spirit_stone`；余额不可为负，任何余额/物品变化必须与 operation ledger 和资产流水同事务。

## 1. 钱包与来源

`new_user` 钱包余额 0；寻仙问道 `player.start_seeking` 发 100，入道 `player.enter_cultivation` 发 200。任务、探索、生产、战斗、摆摊成交和委托是独立 operation，禁止合并新手奖励或把展示金额当余额。

| `ledger_reason` | 可增加 | 可减少 | 说明 |
|:--|:--|:--|:--|
| `onboarding.seeking` / `onboarding.cultivation` | 是 | 否 | 各玩家/operation 唯一 |
| `quest.reward` / `battle.reward` / `exploration.reward` | 是 | 否 | 按任务/战斗/会话唯一 |
| `market.listing_fee` / `market.trade_fee` | 否 | 是 | 系统回收，不退或按订单规则退 |
| `market.sale` / `market.purchase` | 是/否 | 是/否 | 双方账本在同一成交事务 |
| `commission.escrow` / `commission.settlement` | 锁定/释放 | 锁定/支付 | 区分 available 与 locked |

## 2. 固定摆摊：`market.list`

| 参数 | 固定值 |
|:--|--:|
| 可上架物品 | 可交易堆叠物或无绑定唯一实例；禁止凭证、功法、绑定/锁定物 |
| 单笔数量 | 1–99 |
| 单价 | 1–100,000 灵石 |
| 上架费 | 每件 1 灵石，创建成功立即回收，不退款 |
| 成交手续费 | 成交总价 500 bp，向卖方收取，向上取整，至少 1 |
| 有效期 | 24 小时 |
| 同时上架 | 每角色 10 单 |

状态：`draft -> listed -> matched -> settled | cancelled | expired`。创建成功时同时锁物品、扣上架费并写订单；买方购买时锁买方余额，验证卖方物品锁后原子转移物品、支付卖方净额、回收手续费、更新订单。买方容量不足、余额不足、订单过期或物品锁异常时不进入部分成交。卖方只能取消 `listed`，解锁物品且不退上架费；过期 job 解锁物品，重复 job 不重复解锁。

## 3. 生产委托：`commission.create`

v0.1 可委托 `recipe.pill.healing_low`、`recipe.weapon.wood_sword`。委托人设报酬 1–500 灵石与可选材料提供方式，创建时锁报酬；生产者接受后锁材料、精力、工具。成功交付：报酬支付生产者的 9800 bp，平台回收 200 bp；失败：返委托人 8000 bp 报酬和未消耗材料，生产者不获报酬；生产者主动取消 `accepted` 状态时全额解锁。

状态：`draft -> published -> accepted -> locked -> processing -> delivered -> settled`，或 `cancelled/expired/failed`。发布 24h 未接受：全额解锁；processing 24h 超时：用生产快照结算成功/失败，不允许双方重复扣发。

## 4. 参考价、错误与验收

| `item_key` | NPC 回收价 | 摆摊参考价 |
|:--|--:|--:|
| `item.herb.blood_grass` | 2 | 3–8 |
| `item.herb.spirit_leaf` | 5 | 8–15 |
| `item.ore.ironstone` | 4 | 6–12 |
| `item.pill.healing_low` | 20 | 30–60 |
| `item.weapon.wood_sword` | 35 | 50–100 |

NPC 每物品/角色/业务日回收最多 50；超过部分按 50% 价格，回收 operation 仍逐笔审计。错误：`WALLET_INSUFFICIENT`、`MARKET_ITEM_LOCKED`、`MARKET_ORDER_NOT_LISTED`、`MARKET_BUYER_CAPACITY_INSUFFICIENT`、`MARKET_ORDER_EXPIRED`、`COMMISSION_RECIPE_FORBIDDEN`、`COMMISSION_ESCROW_CONFLICT`。关闭后停止新订单，listed/委托按过期规则解锁或恢复结算。验收：双买不超卖；取消/过期不双解锁；手续费向上取整；委托锁定原子；重复成交/领奖返回原结果。