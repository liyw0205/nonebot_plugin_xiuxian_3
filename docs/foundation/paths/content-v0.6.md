# v0.6 道途内容基线：终局道果

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=paths-0.6.0`。道果在第三次天劫试炼中锁定，不能通过普通道途切换、赛季重置或管理员快捷操作修改。

| 道途 | `fruit_key` | 前置与试炼选择 | 终局效果 | 限制 |
|:--|:--|:--|:--|
| 体修 | `fruit.immortal_body` | 体修、完成承伤试炼 | 天劫伤害 -3000 bp | 只对天劫标签伤害生效 |
| 法修 | `fruit.origin_spell` | 法修、完成元素试炼 | 领域能量恢复量 ×2 | 每日恢复仍受 150 上限 |
| 器修 | `fruit.machine_heaven` | 器修、完成机关试炼 | 一件指定机关获得永久耐久化 | 仅一件，不能交易/拆解 |
| 魔修 | `fruit.free_demon` | 魔修、完成契约试炼 | 免疫普通侵蚀增长 | 阵营敌对、心魔与天劫侵蚀仍生效 |
| 妖修 | `fruit.ancestral_king` | 妖修、完成族群试炼 | 可在妖界建立一个族群据点 | 据点受领地维护与赛季规则限制 |
| 辅修 | `fruit.allcraft` | 辅修、完成三类大师作品 | 炼丹/炼器/布阵均视为大师级 | 不能绕过配方、材料、订单与市场限制 |

## 锁定与结局联动

`paths.lock_dao_fruit` 只能由 `trial.dao_choice` 成功回调，输入 `trial_id`、`fruit_key`、`operation_id`。必须匹配当前首要道途，且角色没有已锁定道果。成功后写入不可变 `DaoFruitRecord`：试炼快照、选择、规则版本、效果参数和 operation。失败/超时不扣天劫资源；相同 operation 回放记录，不允许换 fruit。

道果效果仅在 `ascension_ready` 后正式激活；此前可显示预览但不得参与资产结算。选择 `ascend` 时道果随终局角色冻结；选择 `remain_in_world` 时道果保留并受到留界道统/赛季上限约束。

错误：`DAO_FRUIT_PATH_MISMATCH`、`DAO_FRUIT_ALREADY_LOCKED`、`TRIAL_NOT_RESOLVED`、`ENDING_STATE_REQUIRED`。关闭 v0.6 后不创建新锁定，但已有候选角色仍可完成一次结局。验收：道果与首要道途匹配；同一角色只能一个；留界/飞升不重发道果物品；终局回滚不使已锁定道果可重新选择。