# v0.2 经济内容基线：求购单、宗门兑换与金丹市场

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.2`，`rule_version=economy-0.2.0`。新增资源 `merit` 与 `faction_reputation.*` 不可兑换成灵石；它们只用于内容准入/宗门兑换。

## 1. 金丹市场扩展

摆摊单价上限 500,000，手续费仍为 500 bp。允许标签：`market_tag.cloud_iron`、`market_tag.cave_pass`、`market_tag.golden_pill`；标签仅筛选展示，订单仍引用明确 `item_key`/实例，不接受品质通配或模糊名称。

## 2. 求购单：`market.purchase_order`

| 参数 | 数值 |
|:--|--:|
| 同时发布 | 3 单/角色 |
| 数量 | 1–99 |
| 有效期 | 12 小时 |
| 买方锁定 | `quantity*unit_price + ceil(total*500bp)` |
| 成交交付窗口 | 10 分钟 |
| 可求购物 | 明确可交易 `item_key`，不能求购绑定/唯一/凭证 |

状态：`draft -> listed -> matched -> delivered -> settled | cancelled | expired`。卖方匹配时先锁物；买方锁定余额已存在，交付成功后物品转给买方、卖方得总价、平台回收已锁手续费。交付超时：释放卖方物、订单回 `listed`；到期：全额释放买方锁定（包括预锁手续费）。相同 operation 不能匹配两位卖方。

## 3. 宗门仓库兑换

`sect.exchange.<offer_key>` 每位有效宗门成员每天最多 5 次。合同登记：`sect.exchange.foundation_guard`（贡献 30 -> 筑基护脉丹 1）、`sect.exchange.cloud_iron`（贡献 20 -> 云铁 2）、`sect.exchange.golden_core_guard`（贡献 50 -> 金丹护脉丹 1）、`sect.exchange.array_sand`（贡献 10 -> 阵砂 5）。兑换原子扣减宗门库存与个人贡献并写入个人背包；库存/贡献不足不部分扣。

贡献与库存的玩家入口：`宗门每日建设` 要求 UTC 当日三个不同生产/探索会话成功结算，每成员每日一次，增加建设 1、贡献 5；`宗门捐献 灵石|灵叶|止血草|阵砂|云铁 数量` 消耗玩家资源，灵石每 100 增加贡献 1（单次 100–9900、100 的倍数），非绑定原料每件增加贡献 1（单次 1–99）。绑定护脉丹不能直接捐入公共仓库。捐献物品占用仓库物品种类格位，超出容量拒绝且不扣物。`宗门补给 筑基护脉丹|金丹护脉丹` 仅宗主/副宗主可操作：筑基护脉丹消耗仓库灵叶 2、阵砂 1、止血草 1 和公共灵石 100；金丹护脉丹消耗灵叶 3、云铁 1、止血草 2 和公共灵石 200。补给在同一事务中扣原料、加固定库存，带审计记录；云铁和阵砂通过捐献原料入库。建设、捐献、补给和兑换均按 operation 幂等，QQ 官方和 OneBot V11 模拟入口已验收。

错误：`PURCHASE_ORDER_CAP`、`PURCHASE_ITEM_FORBIDDEN`、`PURCHASE_ESCROW_INSUFFICIENT`、`PURCHASE_DELIVERY_EXPIRED`、`SECT_EXCHANGE_DAILY_CAP`、`SECT_STOCK_INSUFFICIENT`。关闭后求购单按过期释放，宗门兑换停止新建。验收：买方手续费锁定/过期全返；两卖方不双成交；明确 item 键校验；宗门库存与贡献同事务；日上限幂等。
