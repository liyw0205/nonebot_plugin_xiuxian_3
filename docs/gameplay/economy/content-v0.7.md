# v0.7 经济内容基线：虚空集市周度补给

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，`rule_version=economy-0.7.0`。
本版把 v0.5 冻结的 `market.void_weekly.<week_id>` 契约接入运行时：此前只有航道终点、终点名称与
航道准入，没有库存、价格、购买用例或持久化。

## 1. 数据合同

`data/经济/虚空集市.json`（kind `void_market`，已登记 `data/内容清单.json`）：

| 稳定键 | 字段 | 值 |
|:--|:--|:--|
| `market.void.defaults` | `location_key` | `void.void_market`（只作为锚点航道终点出现，不在 `地点.json` 中，与 `void.sect_fortress` 同构） |
| | `week_start_weekday` / `week_start_hour_utc` | `1` / `0`（UTC 周一 00:00 换库） |
| | `stock_slots` | `20`（全宿主共享的周库存槽） |
| | `daily_purchase_limit` | `3`（每角色每 UTC 日购买件数） |
| | `binding_seconds` | `86400`（虚空材料首次绑定 24 小时） |
| | `required_realm` / `required_layer` | `void_refining` / `1` |
| | `required_merit` | `500`（与境界二选一） |
| `offer.void_market.void_crystal` | `item.void_crystal` ×1 | 灵石 12000，周库存 4 |
| `offer.void_market.void_anchor` | `item.void_anchor` ×1 | 灵石 5000，周库存 8 |
| `offer.void_market.time_trace` | `item.herb.time_trace` ×1 | 灵石 3000，周库存 8 |

三条报价合计 20 槽，与 `stock_slots` 相等；加载器把「报价库存之和必须等于周库存槽」作为硬校验，
因此新增或减少报价时必须同时调整槽位，不能留下无法售出的空槽。

价格取 v0.5 冻结的「虚晶 12000、锚 5000、时间花 3000」；`时间花` 对应既有材料 `item.herb.time_trace`
（时痕草），不新增物品。三条报价的中文别名（虚晶/晶体、空间锚/锚、时间花/时花）与稳定键一并
参与解析，跨报价重复别名在加载期拒绝。

## 2. 加载期校验

`economy/void_market_content.py` 解析并校验：

- 默认记录必须 `active`、`name`/`desc` 非空；
- `location_key` 必须是已登记的 `world_void_route` 终点（集市只经锚点航道抵达，避免绕开航道准入）；
- ISO 周起始日 1–7、起始小时 0–23；`stock_slots`/`daily_purchase_limit`/`binding_seconds`/`quantity`/
  `price_spirit_stones`/`stock` 为正整数；`required_merit` 非负；
- `required_realm` 必须是已开放境界；物品必须是已开放的 `item` 记录；
- 报价键必须以 `offer.` 开头且唯一，`label`/`name`/`desc` 非空，别名非空且无跨报价冲突；
- 任一条目 `status` 非 `active`、缺字段、非整数或非正数均抛 `ContentError`。

## 3. 运行时与持久化

- `economy/void_market_rules.py`：`VoidMarketDefinition`/`VoidMarketOffer`、`week_start`/`week_id`/
  `week_refresh_at`/`business_date`、`resolve_void_market_offer`、`void_market_missing_requirements`
  （炼虚 L1 **或** 虚空功勋 500）。
- `economy/void_market_repository.py`：`preview_void_market`（只读）与 `purchase_void_market_offer`（单事务）。
- 新表 `void_market_purchases` 记录每次购买的 `offer_key`/`week_id`/`business_date`/`item_key`/数量/
  单价/总额/快照/operation；`void_market_item_bindings` 记录 24 小时绑定（`economy/bindings.py`
  已把它计入活跃绑定总量，绑定期内不能进入摆摊）。库存不落独立计数表，余量由本周购买流水求和推导，
  `BEGIN IMMEDIATE` 串行化购买，因此并发请求不会超卖，只读预览也不产生写入。
- 资产变化复用共享 `apply_player_asset_transition` 与 `economy_ledger_entries`；每次购买写一条灵石
  借记和一条物品贷记。

## 4. 玩家流程与错误

`虚空集市[ 物资名]` 查看本周库期、余量、今日额度、准入状态与三条报价；`购买虚空物资 <物资名> [数量]`
执行购买（默认 1 件，单次不超过每日上限）。

| 情况 | 结果 |
|:--|:--|
| 不在 `void.void_market` | `VOID_MARKET_REQUIREMENT_MISSING`，零写 |
| 境界与虚空功勋均不足 | `VOID_MARKET_REQUIREMENT_MISSING`，零写 |
| 本周库存不足 | `VOID_STOCK_SOLD_OUT`，零写 |
| 今日已购满 3 件 | `VOID_DAILY_PURCHASE_CAP`，零写 |
| 灵石不足 | `BALANCE_INSUFFICIENT`，零写 |
| 未知物资 / 缺参 / 非正整数 / 超过单次上限 | `VOID_MARKET_OFFER_NOT_FOUND`、`INVALID_VOID_MARKET_COMMAND`，零写 |
| 同 operation 重放 | 返回原结果 `idempotent_replay=True`，不重复扣费 |
| 同 operation 不同输入 | `LEDGER_CONFLICT` |
| 写入异常 | `PERSISTENCE_ERROR` 整笔回滚，可原 operation 重试 |

## 5. 呈现

- QQ 原生 Markdown：列表页给每条可购物资附 `购买虚空物资 <中文名>` 蓝字预填链接；单项预览在可购买时
  只附一个「购买此物资」按钮，购买成功后只附一个「再看虚空集市」按钮。列表页不堆按钮网格。
- OneBot/纯文本：链接降级为可读命令，按钮降级为正文「可发送：…」，不保留 `command:`、不暴露
  `offer.*` 等稳定键。
- `修仙帮助 生活` 追加数据驱动的虚空集市报价（中文名 + 价格 + 周库存），不附按钮。

## 6. 边界

不新增物品、地点、通路、敌人、奖池、配方或图鉴；不改航道准入、体力/锚成本、风暴与不稳定语义；
不做跨服转移、玩家间挂单、订单撮合或宗门共享购买；宗门优先权仅在 v0.5 赛季冻结中登记，本版不改变
其窗口与配额语义。关闭集市内容时列表与购买均按内容失败拒绝，已成交记录与绑定不回退。
