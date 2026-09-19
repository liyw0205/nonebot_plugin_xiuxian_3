# v0.5 经济内容基线：虚空限量市场与联盟费用

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.5`，`rule_version=economy-0.5.0`。虚空物品首次绑定 24 小时，跨服转移和订单匹配在绑定期内拒绝。

| `market_key` | 条件 | 限额/费用 | 价格/结算 |
|:--|:--|:--|:--|
| `market.void_weekly.<week_id>` | 炼虚或虚空声望 >=500 | 20 个库存槽、个人每日 3 件 | 虚晶 12000、锚 5000、时间花 3000；固定价原子扣库存 |
| `market.void_material` | 炼虚或声望 >=500 | 6h、手续费 800 bp | 卖方锁物期间不能跨服移动；过期 5 分钟内解锁 |
| `sect.cross_server_war_fee` | 堡垒 active | 公共钱包 5000 | 报名成功回收，不因个人退出退款 |
| `social.alliance_breach_fee` | 联盟提前解除 | 公共钱包 10000 | 双方确认解除后回收 |

虚空市场每日/每周库存由服务端 run ID 创建，`week_id`/`business_date` 与库存/订单唯一；个人限额不和宗门购买共享。虚空材料订单卖方进入锁定后不能跨服移动，但可进行本地只读/非资产操作；过期释放物和移动锁。

错误：`VOID_MARKET_REQUIREMENT_MISSING`、`VOID_DAILY_PURCHASE_CAP`、`VOID_STOCK_SOLD_OUT`、`VOID_SELLER_TRANSFER_LOCKED`、`SECT_WALLET_INSUFFICIENT`。关闭后固定库存只读、旧订单按过期处理。验收：并发购买不超库存；日限额重试稳定；跨服锁解除；公共费用只扣一次；绑定期不绕过。