# v0.4 经济内容基线：领域材料市场

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=economy-0.4.0`。领域材料订单单价上限 2,000,000 灵石，普通成交手续费 600 bp；领域装备首次绑定 12 小时后才能交易。

| `market_key` | 准入/限制 | 费用/期限 | 特殊规则 |
|:--|:--|:--|:--|
| `market.domain_material` | 化神或领域建设委托；最多 5 单/角色 | 12h、手续费 600 bp | 核心成交另收登记费 200，取消不退 |
| `trade.weekly_domain.<week_id>` | 化神、三界贸易周 | 每角色最多 5 次 | 每周 10 个高阶兑换单，按库存锁定 |
| `sect.domain_maintenance` | 宗门等级 >=4 | 日费 2000 灵石 | 公共钱包不足使领域建筑 inactive |

参考价：`item.domain_core` 8,000–15,000，`item.ancient_fruit` 2,000–4,000，祖灵血 1,500–3,000。NPC 不回收领域核心；核心只能由玩家订单/宗门建设流通。订单创建时检查绑定、实例锁、容量和登记费；成交时锁买方余额，转物/扣费/写登记记录同事务。

高阶兑换单由 `event.three_realms_trade_week.<week_id>` 创建，数量、输入、输出和价格在轮次开始固定；关闭/赛季结束时未匹配订单按普通过期解锁。错误：`DOMAIN_MARKET_REQUIREMENT_MISSING`、`DOMAIN_CORE_REGISTRATION_FEE_INSUFFICIENT`、`DOMAIN_WEEKLY_STOCK_SOLD_OUT`、`SECT_MAINTENANCE_WALLET_INSUFFICIENT`。验收：登记费不退；绑定期拦截；库存不超卖；维护 job 不双扣；关闭不影响既成成交。