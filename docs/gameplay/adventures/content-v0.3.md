# v0.3 冒险内容基线：三界悬赏、界隙秘境与主线分歧

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=adventures-0.3.0`。跨界冒险保存阵营/盟约/污染/血脉快照；失败不静默抹除状态。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.demon_relief`：`access.demon_abyss_gate`；接取后获得并交付 `item.food.coarse_spirit_rice` 3 | 4h；每日 1 条；魔界声望 +10、灵石 240；领取时扣除 3 份补给，过期不扣 |
| 悬赏 | `bounty.beast_habitat`：有效 `permit.beast_trade`；接取后完成 `dispatch.beast_relocation` success 2 次 | 48h；每日 1 条；妖界声望 +10、`codex.story.beast_habitat`；只计接取后新结算的唯一来源 operation |
| 秘境 | `instance.secret_realm.boundary_rift`：元婴 L1、2–5 人确认 | 6 节点、30 体力/队；首通图鉴、普通神魂材料、主线旗标；每周 1 |
| 秘境 | `instance.secret_realm.demon_abyss`：魔界声望 200 | 4 节点、20 体力；污染风险 +50 bp；首通名望/故事线索 |
| 主线 | `story.mainline.three_realms` | 元婴 L1；调停、契约、共生三线，选择一线后按序完成 5 关；结局写故事、对应三界声望 1000、`item.token.rebuild_path` 和 `story.mainline.three_realms` 许可旗标 |
| 斗法留影 | `combat.replay.v0.3` | 保留 90 天/1000 场；公开战报脱敏；跨界战日志只显示区域和队伍编号 |

跨界秘境需要队伍成员逐一确认，任一成员不满足则不扣费；战斗中途掉线由队长/恢复任务结算。悬赏和主线可发正常修为，但必须经 progression/reward service，禁止直接写字段。

`bounty.demon_relief` 使用 `content-0.3` / `adventures-0.3.0`：角色须已通过魔界风险确认并持有
`access.demon_abyss_gate`，不另加境界或地点门槛。进度以接取时 `item.food.coarse_spirit_rice` 数量为基线，
只计接取后新增量；领取事务再核验并扣除 3 份，失败/过期不扣货、不发奖。奖励写入 `faction_reputation.demon`
与灵石，重复 operation 回放原结果。当前实现与适配器验收见[冒险域](README.md)和[当前开发状态](../../current-status.md)。

`bounty.beast_habitat` 使用 `content-0.3` / `adventures-0.3.0`：角色申请时须持有效 `permit.beast_trade`。
进度按接取时间之后已结算的 `specials.dispatch.settled` 事件计算，只接受 `dispatch.beast_relocation`
且 `outcome=success` 的唯一来源 operation；接取时在途的派遣编号写入基线，已结算来源也因结算时间早于接取时间而不计入。领取事务
写入 `faction_reputation.beast` +10 并首次发现 `codex.story.beast_habitat`；不足两次或过期均不发奖励。
`dispatch.demon_relief` / `dispatch.beast_relocation` 与贸易许可的稳定键、成本、时长、风险、返还及奖励
均以 [v0.3 特色玩法内容基线](../specials/content-v0.3.md) 和 [v0.3 常驻经营内容基线](../livelihood/content-v0.3.md) 为准。

## `instance.secret_realm.demon_abyss` 合同缺口

该稳定键已登记但尚不能开放。当前表格只定义了声望门槛、节点数、体力和首通奖励类别；实现前必须补齐以下内容，不得从魔渊探索或 `demon.fallen_ruins` 队伍副本推导：

- 秘境地点、境界和正式准入旗标；魔界声望 `>=200` 是否为唯一准入条件。
- 四个节点的稳定顺序及各节点行为；每周额度与过期、战败时体力/门票的处理。
- “污染风险 +50 bp”的单位、触发时点、概率/效果和快照字段；不得把它当作污染点数或战斗惩罚直接套用。
- 首通名望对应的声望域、数值和奖励稳定键；故事线索的稳定键、数量；重复通关奖励及其随机/冻结规则。

上述字段闭合并补充双适配器验收前，保持 `locked`，不创建新运行时入口。
