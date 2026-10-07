# 经济域：钱包与订单模型

`Wallet`：角色、货币键、可用余额、锁定余额和更新时间。

`LedgerEntry`：来源、目标、前值、变化量、后值、来源类型、来源 ID 和 operation ID。

`MarketOrder`：订单 ID、发布者、执行者、类型、物品/资源、数量、单价、手续费、锁定记录、状态、过期时间和更新时间。

当前市场支持固定价格摆摊、简单玩家委托和限量拍卖；复杂竞价和跨服市场后置。

`CrossRealmTrade`：固定贸易键、角色、UTC 周起始日、地点、输入、灵石成本、输出、绑定到期、
周次数与声望准入快照和 operation。`ItemBinding` 记录交易输出的角色绑定数量和到期时间；
摆摊创建必须从可用库存中扣除仍在绑定期内的数量。

`AuctionLot`：UTC 周起始日、卖方、物品锁、起拍价、当前出价、结束时间、结算截止时间、状态、拍品名称和完整规则快照；
`AuctionBid`：竞价者、锁定灵石、状态和 operation。被超越、成交或超时流拍都必须原子释放锁定资产。

拍卖规则快照包含 `key`、`name`、`desc`、`slot_limit`、`duration_seconds`、`settlement_grace_seconds`、
`min_quantity`、`max_quantity`、`min_starting_bid` 和 `min_increment_bp`。名称和说明为非空文本，所有数值为正整数，数量上限不得低于下限；不接受布尔值、字符串数值、缺字段或额外字段。物品名称、数量、起拍价和规则在发布时冻结，不以当前内容补齐历史拍品。
