# v0.6 特色玩法内容基线：道统回响与终局旁线

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=specials-0.6.0`。终局特色玩法只记录世界回响、道统服务和故事观察；不能发放/交换道果、天劫 token、飞升凭证、飞升功勋或直接改变 `ending_state`。

| 类型 | 稳定键与准入 | 参数与结算 |
|:--|:--|:--|
| 挂机 | `idle.dao_settlement_watch`：参与 `project.dao_settlement` | 12h；灵石 180–280、建设券 2、道统图鉴线索；超时灵石 90 |
| 派遣 | `dispatch.dao_service`：道统服务资格或信誉 >=80 | 8h；居所/维护服务；成功名望 +8、信誉 +4、故事线索；不产终局物 |
| 派遣 | `dispatch.ascension_supply`：普通角色可参加 | 6h；疗伤丹/灵米/维修物；名望 +6、运输券；不得影响天劫结果 |
| 图鉴 | `codex.dao.service_*`、`codex.ending.public_*` | 集齐道统服务 6 条：公开世界志、展示称号；私密结局不计入 |
| 试炼塔 | `tower.void_spire` 31–60：合道 L1 或道统服务名望 700 | 每周 1 次；首通故事/图鉴/展示；无道果/功勋/终局装备 |
| 竞技场 | `arena.dao_echo`：合道 L1 或公开道统演练资格 | 异步演练，赛季只给称号/名望/服务权限；飞升角色只可作为只读历史快照 |
| 剧情 | `story.dao_echoes` | 建设者/见证者/远行者多结局；结局写展示旗标和新篇章预览，不能替代 `ascension.choose_ending` |

终局内容关闭时不建新旁线会话；已 `ending_pending` 故事可在 7 天内完成一次展示结局领取。任何 attempt 将 `resource.dao_fruit_progress`、`resource.ascension_merit`、`resource.tribulation_debt` 或 `ending_state` 写入特色玩法操作的行为必须拒绝 `ENDGAME_ASSET_FORBIDDEN`。