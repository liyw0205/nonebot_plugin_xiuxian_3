# v0.6 经济内容基线：终局材料与经济隔离

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=economy-0.6.0`。终局经济不得通过普通市场向新角色或基础市场回流。

| `market_key` | 可交易 | 禁止交易 | 参数 |
|:--|:--|:--|:--|
| `market.dao_fragment` | 暂无（v0.6 未开放） | `item.dao_fruit_fragment`、飞升凭证、道果、终局法器、结局称号、进度/功勋 | 道果碎片绑定不可交易；该市场切片仍关闭 |
| `dao.settlement_construction` | 道统建设材料/服务 | 核心权限、投票、成员席位 | 使用世界功勋，不可灵石购买 |
| `season.final_reward` | 无普通交易 | 所有结局奖励 | 只发称号、展示物、新篇章资格 |

终局订单创建时验证角色 `ending_state=none|pending`；一旦 `ascended` 或 `remained`，自动取消未完成终局订单、原路释放锁定碎片/灵石。飞升角色的终局资产移动到终局表，留界角色的道果材料绑定道统，不进入普通背包市场。

赛季结束：清理临时功勋、虚空订单、未完成终局求购；永久装备保留，历史成交/结局不删除。错误：`ENDGAME_ITEM_FORBIDDEN`、`DAO_FRAGMENT_SEASON_CAP`、`ENDING_STATE_MARKET_LOCKED`、`SETTLEMENT_PERMISSION_DENIED`。验收：禁物在锁定前拒绝；赛季限额；结局自动取消一次；世界功勋不转灵石；终局奖励不回流。
