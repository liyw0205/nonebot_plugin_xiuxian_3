# 经济域：用例、风控与验收

## 用例

`credit_wallet`、`debit_wallet`、`create_market_order`、`buy_market_order`、`cancel_market_order`、`expire_market_order`、`create_service_order`、`settle_order`、`execute_cross_realm_trade`、`create_purchase_order`、`match_purchase_order`、`deliver_purchase_order`、`cancel_purchase_order`、`expire_purchase_order`、`create_auction`、`bid_auction`、`settle_auction`、`list_auctions`。

## 错误码

`WALLET_NOT_FOUND`、`BALANCE_INSUFFICIENT`、`LOCKED_BALANCE`、`CURRENCY_INVALID`、`LEDGER_CONFLICT`、`ORDER_NOT_FOUND`、`ORDER_EXPIRED`、`ORDER_ALREADY_SETTLED`、`PRICE_OUT_OF_RANGE`。
固定跨界贸易另有 `CROSS_REALM_TRADE_PERMISSION_DENIED`、`TRADE_WEEKLY_CAP`、
`TRADE_INPUT_INSUFFICIENT`、`ITEM_BINDING_ACTIVE`。
限量拍卖另有 `AUCTION_SLOT_FULL`、`AUCTION_BID_TOO_LOW`、`AUCTION_SETTLEMENT_EXPIRED`、`AUCTION_STATE_CONFLICT`、
`AUCTION_ITEM_LOCKED`。
物品使用若数量全部由摆摊、求购或拍卖保留，返回 `ITEM_RESERVED`，不扣除背包物品。

## 风控

限制单笔价格、数量和每日成交；记录自买自卖、循环转账和异常短时成交；管理员补偿只新增流水，不覆盖原流水。

## 验收

求购创建先按 operation ID 和原始物品选择器核对历史请求；只有新请求才解析现行物品内容。订单快照冻结物品展示名，
匹配、成交、列表和创建重放均不因物品改名或关闭而重新解释。不同创建输入仍返回 `LEDGER_CONFLICT`。

余额不足不锁卖方物品；成交重试只转移一次；撤单完整解锁；清理不重复退款；流水可重建余额。
摆摊、求购匹配和拍卖创建必须汇总三种交易锁；物品使用不得扣除已保留数量，释放锁后相同未完成 operation 可重新执行；拒绝时不得留下物品、费用、效果或 operation 写入。
固定贸易须覆盖魔渊集市/万兽山/三界贸易口地点准入、周限额、失败不扣、24 小时绑定、绑定期摆摊拦截和 QQ 官方/OneBot V11 operation 幂等；三界贸易口还需同时校验魔界与妖界声望 200。
求购还须覆盖物品改名后的跨 runtime 原 operation 重放、冻结名称、资产/订单唯一性、不同输入冲突、新请求按当前内容拒绝，
并在 QQ 官方与 OneBot V11 实际命令路径验收。

拍卖需在 QQ 官方与 OneBot V11 覆盖真实发布、竞价、被超价退款、成交、无竞价流拍和超恢复窗口退款。修改临时内容的槽位、时长、数量/起拍价门槛与加价幅度须影响新拍品，旧拍品仍按完整快照执行；物品或拍卖内容改名、关闭、移除后的列表、结算和原 operation 跨重启回放不受影响。换输入冲突、坏 JSON/快照、并发、流水或账本故障均原子拒绝并可沿原请求重试；不改变既有物品品质准入、手续费或跨交易库存保留规则。
