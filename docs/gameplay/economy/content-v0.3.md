# v0.3 经济内容基线：三界贸易与限量拍卖

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=economy-0.3.0`。跨界订单记录卖方/买方阵营、获得区域、首次绑定到期和盟约；不满足贸易许可的订单不能创建。

## 1. 三界固定贸易

| `trade_key` | 输入 | 输出 | 每角色/周上限 | 绑定 |
|:--|:--|:--|--:|:--|
| `trade.xuantian_to_demon` | 云铁 10、灵石 200 | `item.demon_core` 1 | 5 | 24h |
| `trade.xuantian_to_beast` | 灵叶 10、灵石 200 | `item.beast_blood` 1 | 5 | 24h |
| `trade.three_realms` | 魔核 2、妖血 2 | `item.soul_crystal` 1 | 3 | 24h |

兑换在 `market.trade` 单 operation 中验证输入、周计数、阵营许可与背包容量，再扣输入/发输出；失败不扣任何输入。周计数按服务器周一 00:00，重试不增加。赛季结束不回滚已完成兑换，未完成贸易会话取消并返还锁定输入。

## 2. 跨界订单与拍卖试运行

跨界求购有效期 12 小时、手续费 800 bp；卖方/物品区域来源写订单，物品首次绑定未到期不能匹配。`auction.weekly.<week_id>` 每周一场、20 个槽，只允许非绑定 `heaven` 以下实例。竞价：出价者锁最高出价，下一价必须至少当前价 +5%；被超越后释放旧锁；结束时最高价原子成交，流拍解锁物品。拍卖结束后 10 分钟内支付/交付恢复窗口，超时按流拍处理。

赛季市场 `market.season.<season_id>` 只记录成交价统计，不继承未完成订单；季末 job 取消未完成订单并原路释放锁定，不删除历史成交。

错误：`CROSS_REALM_TRADE_PERMISSION_DENIED`、`TRADE_WEEKLY_CAP`、`ITEM_BINDING_ACTIVE`、`AUCTION_SLOT_FULL`、`AUCTION_BID_TOO_LOW`、`AUCTION_SETTLEMENT_EXPIRED`。验收：三界贸易周限额；绑定拦截；超价释放锁；拍卖成交唯一；季末取消不影响历史统计。