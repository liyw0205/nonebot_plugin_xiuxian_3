# 经济域：用例、风控与验收

## 用例

`credit_wallet`、`debit_wallet`、`create_market_order`、`buy_market_order`、`cancel_market_order`、`expire_market_order`、`create_service_order`、`settle_order`、`execute_cross_realm_trade`。

## 错误码

`WALLET_NOT_FOUND`、`BALANCE_INSUFFICIENT`、`LOCKED_BALANCE`、`CURRENCY_INVALID`、`LEDGER_CONFLICT`、`ORDER_NOT_FOUND`、`ORDER_EXPIRED`、`ORDER_ALREADY_SETTLED`、`PRICE_OUT_OF_RANGE`。
固定跨界贸易另有 `CROSS_REALM_TRADE_PERMISSION_DENIED`、`TRADE_WEEKLY_CAP`、
`TRADE_INPUT_INSUFFICIENT`、`ITEM_BINDING_ACTIVE`。

## 风控

限制单笔价格、数量和每日成交；记录自买自卖、循环转账和异常短时成交；管理员补偿只新增流水，不覆盖原流水。

## 验收

余额不足不锁卖方物品；成交重试只转移一次；撤单完整解锁；清理不重复退款；流水可重建余额。
固定贸易须覆盖魔渊集市/万兽山/三界贸易口地点准入、周限额、失败不扣、24 小时绑定、绑定期摆摊拦截和 QQ 官方/OneBot V11 operation 幂等；三界贸易口还需同时校验魔界与妖界声望 200。
