# v0.6 物品内容基线：天劫与飞升凭证

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=items-0.6.0`。终局物品不可自由交易；所有授予与消耗必须关联天劫轮次或结局 operation。

| `item_key` | 类型/堆叠 | 绑定/交易 | 用途与限制 | 来源 |
|:--|:--|:--|:--|:--|
| `item.tribulation_token` | 天劫凭证，9 | 绑定 | 前往天劫台消耗 1；每次三阶段试炼另消耗 1；最终战不消耗 | 道统任务、赛季贡献 |
| `item.dao_fruit_fragment` | 道果材料，99 | 绑定 | 合道前置 10；试炼奖励/终局配方 | 天劫试炼 |
| `item.ascension_certificate` | 资格凭证，1 | 绑定 | 最终战创建会话前锁定；最终战失败不消耗 | 三次试炼成功、道统授予 |
| `item.weapon.dao_origin` | 终局法器，唯一 | 永久绑定 | 道果进度获得 +1000 bp（受试炼上限）；不可拆解 | 终局首领唯一奖励 |
| `item.title.ascended` | 称号，唯一 | 永久绑定 | 飞升/留界展示；不提供货币或伤害 | 结局 operation |
| `item.tribulation_guard` | 天劫保护阵，1 | 绑定至下一试炼 | 失败时 `resource.tribulation_debt` 增量 -5，最低 0 | `recipe.tribulation.guard` |

天劫 token 在天劫台移动成功创建和试炼成功创建时分别消耗；准入失败、活动会话互斥或 operation 冲突时不扣除。完成三次试炼链至少需要 4 张天劫凭证（1 张移动、每次试炼 1 张）。道果碎片不能直接兑换灵石、世界功勋或飞升资格。飞升凭证若最终战会话超时，保持锁定并由恢复任务按原战斗快照结算或显式返还；不得静默消失。

`weapon.dao_origin` 每角色最多一件；再次获得时转为道果进度 50，且转换 operation 引用原掉落池。选择 `remain_in_world` 的角色不会获得飞升凭证，但可以获得绑定称号；选择 `ascend` 后所有未使用天劫道具冻结在终局资产表，不能回流普通市场。

错误：`TRIBULATION_TOKEN_INSUFFICIENT`、`ASCENSION_CERTIFICATE_LOCKED`、`ENDGAME_ITEM_ALREADY_GRANTED`、`ENDING_STATE_CONFLICT`。关闭 v0.6 后停止新终局掉落；已有凭证/会话继续可读与恢复。验收：token 不双耗；最终战失败不耗凭证；终局法器唯一转换稳定；飞升/留界物品差异正确；恢复任务不丢锁定凭证。
