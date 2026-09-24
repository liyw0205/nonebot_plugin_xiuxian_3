# v0.6 生产内容基线：终局自制与道统服务

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=production-0.6.0`。终局配方不可委托、不可交易、不可由协助者代工，只能角色本人在 `dao.origin_gate` 使用，且操作关联天劫/结局状态。

| `recipe_key` | 前置 | 输入 | 时长/产出 | 限制/失败 |
|:--|:--|:--|:--|:--|
| `recipe.dao.fruit_fragment` | 合道、道果试炼开启 | 道果碎片 10、神魂晶 5 | 20 分钟 / 道果进度 +100 | 每试炼链最多 3；失败不加进度，返碎片 5 |
| `recipe.tribulation.guard` | 渡劫准备、领域已选 | 天劫 token 1、领域核心 3 | 30 分钟 / `item.tribulation_guard` 1 | 每次天劫最多 1；失败 token 不返 |
| `recipe.ascension.certificate` | 三试炼成功、道果进度 >=800、功勋 >=1000 | 世界功勋 1000；道果进度只作门槛、不扣除 | 10 分钟 / `item.ascension_certificate` 1 | 每角色 1；失败返还世界功勋，仅记录诊断 |

上述 `recipe.dao.*`、`recipe.tribulation.*` 和 `recipe.ascension.*` 道源门终局配方不可委托、不可交易、不可由协助者代工，只能角色本人在 `dao.origin_gate` 使用。道果加工只允许 `endgame_status=dao_union` 或 `tribulation`；保护阵和飞升凭证只允许 `endgame_status=tribulation`。终局配方会话与天劫试炼会话互斥，二者的启动事务彼此检查活动会话；配方创建快照冻结当时的终局状态。进入 `ascension_ready`、飞升或留界状态后，不再开放这些终局配方。

当前终局配方使用启动 operation ID 的 BLAKE2b 摘要生成稳定检定值，`roll_bp < 8000` 成功；相同 operation 重放原结果。道果加工失败返还 5 个道果碎片，其他投入按配方失败语义处理；道果进度总上限为 1,300。

`item.tribulation_guard` 只能在下一次天劫试炼开始时锁定：失败时使债务增加量 -5（最低 0），成功不消耗；最终战不可使用。飞升凭证成功产出后立即绑定，不能用于普通市场、拆解或赠送。

错误：`ENDGAME_RECIPE_CONTEXT_INVALID`、`DAO_PROGRESS_INSUFFICIENT`、`ASCENSION_CERTIFICATE_ALREADY_CREATED`、`TRIBULATION_GUARD_ALREADY_PREPARED`。关闭后不创建新终局订单，已 processing 订单只可恢复结算。验收：终局配方不能委托；凭证世界功勋启动时扣除、失败返还，道果进度仅作门槛不扣；保护阵消耗语义正确；凭证唯一；历史终局订单可读/可恢复。

## 2. 炼虚职业大师作品

职业作品必须在合道资格任务之前由玩家本人生产。全部配方要求 `void_refining` L10，不要求 `dao.origin_gate` 地点；当前所在地点、道途、辅修、境界、输入、输出、失败返还、质量检定、内容版本和规则版本在普通 `production_orders` 快照中冻结。每个配方每日限 1 次，个人订单 24 小时内领取，过期订单按原快照恢复结算。质量公式沿用生产 v0.1：成功阈值 4,500 bp，operation 随机质量为 0/500/1,000 bp；大师作品没有额外高品质数量。失败不产出作品，输入按表返还；相同 operation 只结算一次。大师作品不可交易，也不进入生产委托配方白名单。

| `recipe_key` | 道途/辅修 | 输入 | 精力/时长 | 成功产出 | 失败返还 |
|:--|:--|:--|:--|:--|:--|
| `recipe.masterwork.body` | 体修 | 云铁 20、领域核心 2 | 20 / 2 小时 | `item.masterwork.body` 1 | 云铁 10、领域核心 1 |
| `recipe.masterwork.spell` | 法修 | 虚空晶 20、神魂晶 6 | 20 / 2 小时 | `item.masterwork.spell` 1 | 虚空晶 10、神魂晶 3 |
| `recipe.masterwork.device` | 器修 | 云铁 15、虚空晶 10、领域核心 1 | 20 / 2 小时 | `item.masterwork.device` 1 | 云铁 8、虚空晶 5、领域核心 1 |
| `recipe.masterwork.demonic` | 魔修 | 魔核 12、神魂晶 6 | 20 / 2 小时 | `item.masterwork.demonic` 1 | 魔核 6、神魂晶 3 |
| `recipe.masterwork.beast` | 妖修 | 兽血 12、虚空晶 8 | 20 / 2 小时 | `item.masterwork.beast` 1 | 兽血 6、虚空晶 4 |
| `recipe.masterwork.alchemy` | 辅修、任一合法辅修 | 止血草 20、神魂晶 3、领域核心 1 | 15 / 90 分钟 | `item.masterwork.alchemy` 1 | 止血草 10、神魂晶 1 |
| `recipe.masterwork.artifice` | 辅修、任一合法辅修 | 云铁 15、虚空晶 5 | 15 / 90 分钟 | `item.masterwork.artifice` 1 | 云铁 7、虚空晶 2 |
| `recipe.masterwork.formation` | 辅修、任一合法辅修 | 领域核心 2、虚空晶 5 | 15 / 90 分钟 | `item.masterwork.formation` 1 | 领域核心 1、虚空晶 2 |
| `recipe.masterwork.support` | 辅修、任一合法辅修 | 炼丹/炼器/布阵大师作品各 1 | 5 / 30 分钟 | `item.masterwork.support` 1 | 三件辅修作品各返还 1 |

输入表中的道具使用已登记稳定键：云铁 `item.material.cloud_iron`、虚空晶 `item.void_crystal`、神魂晶 `item.soul_crystal`、领域核心 `item.domain_core`、魔核 `item.demon_core`、兽血 `item.beast_blood`。职业作品只从成功生产订单发放；高品质不增加作品数量。三种辅修作品必须分别由对应个人生产订单获得，随后才能开始三艺合成。`交付合道作品` 消费与玩家首要道途对应的最终 `item.masterwork.*`，不回写、不重复发放；关闭配方只阻止新订单，已 processing 订单按快照领取或恢复。
