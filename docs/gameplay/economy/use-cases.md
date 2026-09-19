# 经济域：用例、风控与验收

## 用例

`credit_wallet`、`debit_wallet`、`create_market_order`、`buy_market_order`、`cancel_market_order`、`expire_market_order`、`create_service_order`、`settle_order`。

## 错误码

`WALLET_NOT_FOUND`、`BALANCE_INSUFFICIENT`、`LOCKED_BALANCE`、`CURRENCY_INVALID`、`LEDGER_CONFLICT`、`ORDER_NOT_FOUND`、`ORDER_EXPIRED`、`ORDER_ALREADY_SETTLED`、`PRICE_OUT_OF_RANGE`。

## 风控

限制单笔价格、数量和每日成交；记录自买自卖、循环转账和异常短时成交；管理员补偿只新增流水，不覆盖原流水。

## 验收

余额不足不锁卖方物品；成交重试只转移一次；撤单完整解锁；清理不重复退款；流水可重建余额。