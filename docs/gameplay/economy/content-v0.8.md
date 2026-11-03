# v0.8 经济内容基线：虚空物资寄售

`docs/gameplay/economy/content-v0.5.md` 冻结了 `market.void_material`：准入「炼虚或声望 >=500」、
「6h、手续费 800 bp」、「卖方锁物期间不能跨服移动；过期 5 分钟内解锁」。此前没有任何数据、
表或命令承接它；通用摆摊与竞价拍卖都不提供「寄售锁定 + 到期退还 + 8% 手续费」这套语义。

## 数据合同

`data/经济/虚空物资寄售.json`（kind `void_material_market`，`market.void_material.defaults`）：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `listing_hours` | 6 | 挂单时长，到期自动退还 |
| `fee_bp` | 800 | 成交手续费（8%），向下取整 |
| `expire_grace_minutes` | 5 | 仅用于「即将解锁」提示，不阻断退还 |
| `max_listings_per_player` | 5 | 同时挂单上限 |
| `admission` | `void_refining` L1 **或** `void_merit` 500 | 二者满足其一即可 |
| `allowed_item_keys` | 虚空晶体/虚空锚/神魂晶/雾隐核心/灵泉水 | 必须真实 `tradeable` 且非 `character_bound` |

白名单而不是标签：仓内物品没有任何 `void` 标签（实测标签集合为 artifice/qi/foundation/…），
按标签过滤会让市场空转。加载器因此改为逐键校验「存在 + 可交易 + 非角色绑定」，并拒绝重复键。

## 校验与迁移边界

`economy/void_material_content.py` 校验字段集、`listing_hours` 1–72、`fee_bp` 0–2000、
`expire_grace_minutes` 0–60、`max_listings_per_player` 1–50、准入境界存在且层区间合法、
`merit_key` 白名单、物品白名单逐项可交易且非绑定、别名非空；非法抛 `ContentError` 并在导入期构建。
新增 `void_material_listings`、`void_material_trades` 两表，`CREATE TABLE IF NOT EXISTS`，旧库无需迁移。

## 运行时

- **锁定由数据表达**：挂单时把数量从卖家 `inventory_json` 扣除并写进 listing 行，物品只存在于挂单里，
  因此不可能「一物两卖」，也不需要额外锁表。
- **挂牌**：准入、白名单、数量/单价为正、个人挂单上限、持有量，逐项校验后原子扣物。
- **成交**：买家用**一次 delta 事务**同时付灵石并收物品，卖家按 `gross - fee` 入账；
  手续费直接销毁（不落入任何账户）。自己买自己的单被拒；余额不足不改变任何状态。
- **撤下/到期**：撤下仅限卖家且仅 `listed`；到期在读路径惰性推进（`listed` 且 `expires_at <= now`
  → `expired` 并原样退还），不依赖后台任务。
- 全部写操作单事务 + `operations` 幂等，同一 operation 重放返回原结果，输入不一致抛
  `OperationConflictError`。单服行为，不做跨服撮合或玩家间直接转账。

## 命令与呈现

`虚空寄售`（别名 `寄售列表`）、`寄售物资 <物品> <数量> <单价>`、`购入寄售 <序号>`、`撤下寄售 <序号>`。
错误码：`VOID_MARKET_ADMISSION`、`VOID_MARKET_ITEM_FORBIDDEN`、`VOID_MARKET_LIMIT`、
`VOID_MARKET_NOT_ENOUGH_ITEMS`、`VOID_MARKET_NOT_FOUND`、`VOID_MARKET_OWN_LISTING`、
`VOID_MARKET_INSUFFICIENT`、`VOID_MARKET_STATE`、`INVALID_VOID_MARKET_COMMAND`、`LEDGER_CONFLICT`，
失败零写。

QQ 原生 Markdown 列表每行给 `购入寄售 <序号>` 蓝字预填，有在售单时只挂一个「购入第一单」按钮；
OneBot 与纯文本降级为可读文本，不暴露稳定键。`修仙帮助 生活` 追加寄售段。

## 非目标

不改 `market.void_weekly`（虚空集市周补给）与拍卖语义、不共享其表；不做批量挂单、改价、
跨服撮合或玩家间直接转账；手续费不进入任何回收账户。
