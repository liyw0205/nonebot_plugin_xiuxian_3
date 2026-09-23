# v0.6 生产内容基线：终局自制与道统服务

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=production-0.6.0`。终局配方不可委托、不可交易、不可由协助者代工，只能角色本人在 `dao.origin_gate` 使用，且操作关联天劫/结局状态。

| `recipe_key` | 前置 | 输入 | 时长/产出 | 限制/失败 |
|:--|:--|:--|:--|:--|
| `recipe.dao.fruit_fragment` | 合道、道果试炼开启 | 道果碎片 10、神魂晶 5 | 20 分钟 / 道果进度 +100 | 每试炼链最多 3；失败不加进度，返碎片 5 |
| `recipe.tribulation.guard` | 渡劫准备、领域已选 | 天劫 token 1、领域核心 3 | 30 分钟 / `item.tribulation_guard` 1 | 每次天劫最多 1；失败 token 不返 |
| `recipe.ascension.certificate` | 三试炼成功、道果进度 >=800、功勋 >=1000 | 世界功勋 1000；道果进度只作门槛、不扣除 | 10 分钟 / `item.ascension_certificate` 1 | 每角色 1；失败返还世界功勋，仅记录诊断 |

当前终局配方使用启动 operation ID 的 BLAKE2b 摘要生成稳定检定值，`roll_bp < 8000` 成功；相同 operation 重放原结果。道果加工失败返还 5 个道果碎片，其他投入按配方失败语义处理；道果进度总上限为 1,300。

`item.tribulation_guard` 只能在下一次天劫试炼开始时锁定：失败时使债务增加量 -5（最低 0），成功不消耗；最终战不可使用。飞升凭证成功产出后立即绑定，不能用于普通市场、拆解或赠送。

错误：`ENDGAME_RECIPE_CONTEXT_INVALID`、`DAO_PROGRESS_INSUFFICIENT`、`ASCENSION_CERTIFICATE_ALREADY_CREATED`、`TRIBULATION_GUARD_ALREADY_PREPARED`。关闭后不创建新终局订单，已 processing 订单只可恢复结算。验收：终局配方不能委托；凭证世界功勋启动时扣除、失败返还，道果进度仅作门槛不扣；保护阵消耗语义正确；凭证唯一；历史终局订单可读/可恢复。
