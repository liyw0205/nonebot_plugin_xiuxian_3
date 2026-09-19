# v0.6 冒险内容基线：终局悬赏、道源秘境与飞升旁线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=adventures-0.6.0`。终局冒险只能读取终局资格，不能替代天劫试炼、最终战或结局选择。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.dao_origin_service`：道统服务资格 | 完成公共服务 3；12h；道统名望 +20、故事图鉴 |
| 悬赏 | `bounty.ascension_supply`：普通角色也可参加 | 交付疗伤/维修物 5；8h；世界功勋 50、灵石 300；不得发飞升功勋 |
| 秘境 | `instance.secret_realm.dao_origin`：合道 L1、道源许可 | 8 节点、60 体力/队；首通新篇章线索/展示；每角色 1 次 |
| 秘境 | `instance.secret_realm.heaven_echo`：渡劫 L1、非最终战 | 3 节点、天劫债不变；首通结局旁线旗标 |
| 主线 | `story.mainline.dao_echoes` | 建设者/见证者/远行者三线各 10 关；只写故事/服务/图鉴旗标 |
| 斗法留影 | `combat.replay.v0.6` | 终局战日志永久保留但默认私有；公开只显示脱敏摘要和结局编号 |

禁止任何 `bounty`/`instance`/`mainline` operation 写 `ending_state`、道果、天劫债、飞升凭证、`resource.ascension_merit`。最终战与 `ascension.choose_ending` 仍是唯一终局写入口。