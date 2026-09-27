# v0.3 冒险内容基线：三界悬赏、界隙秘境与主线分歧

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=adventures-0.3.0`。跨界冒险保存阵营/盟约/污染/血脉快照；失败不静默抹除状态。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.demon_relief`：`access.demon_abyss_gate`；接取后获得并交付 `item.food.coarse_spirit_rice` 3 | 4h；每日 1 条；魔界声望 +10、灵石 240；领取时扣除 3 份补给，过期不扣 |
| 悬赏 | `bounty.beast_habitat`：有效 `permit.beast_trade`；接取后完成 `dispatch.beast_relocation` success 2 次 | 48h；每日 1 条；妖界声望 +10、`codex.story.beast_habitat`；只计接取后新结算的唯一来源 operation |
| 秘境 | `instance.secret_realm.boundary_rift`：`cave.boundary_realm`、元婴 L1、`story.mainline.three_realms`、2–5 人确认 | 固定 6 节点、每人 30 体力、队长 1 枚 `item.soul_crystal`；每名成员每 UTC 周尝试 1 次 |
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

## `instance.secret_realm.boundary_rift` 合同

该秘境使用 `content-0.3` / `adventures-0.3.1`，与 `cave.boundary_realm` 界隙队伍战是两个独立稳定键和会话。队伍须使用“界隙裂隙秘境”专用队伍类型，在 `cave.boundary_realm` 创建；2–5 名成员都须达到元婴 L1、持有 `story.mainline.three_realms` 故事证据并逐一确认。任一成员校验失败时整队拒绝，不扣资源或额度。

路线固定为 `rift_approach -> shattered_path -> cross_realm_sentinel -> soul_current -> boundary_watcher -> rift_seal`。每个节点只能由队长按顺序确认；`shattered_path` 记录 `inner|outer` 路径选择，不改变战斗数值。第三节点使用服务端自动战 `enemy.cross_realm_sentinel`，第五节点使用 `enemy.boundary_watcher`；客户端不能提交战斗动作或结果。守望者沿用 `combat-0.3.0` 的战斗快照、倒地复起和时间轴规则，第 5/10 回合至少两人防御才能避免全队神魂冲击。

成功进入时，原子扣除每名成员 30 体力及队长 1 枚 `item.soul_crystal`，并为每名成员预占当期 UTC 周唯一尝试额度。战败或 60 分钟会话过期均不退资源、不返额度；战斗启动失败会退还入口成本并释放本周额度，允许重新进入。进行中全员被会话锁定，不能退出队伍、开始其他长行动或加入另一秘境。节点、成员、战斗 ID、随机种子、内容/规则版本和入场资格在创建时冻结；服务重启后按保存的节点与战斗 operation 续跑，已结算节点不重放奖励。

首通按角色独立判定：每名首次成功的成员各获得 `item.soul_crystal` 1、发现 `codex.route.boundary`，并写入 `story.boundary_rift` 故事旗标。再次成功每名成员获得 `item.soul_crystal` 1，不重复发现图鉴或改写旗标。失败不发秘境奖励；遭遇战自身的失败神魂疲劳规则仍生效。唯一首通以角色/秘境键约束，领奖与完成状态在同一事务提交。

进入命令为 `进入秘境 界隙裂隙`；随后队长使用 `选择秘境节点 <裂隙入口|破碎岔路 内|外|跨界哨卫|神魂潮汐|界隙守望者|裂隙封印>` 按序推进，使用 `结算界隙裂隙秘境` 推进自动战或领取完成奖励。QQ 官方和 OneBot V11 必须分别验证混合队伍、准入原子拒绝、路径顺序、两场自动战、时间轴防御、首通/重复奖励、失败/过期成本、额度、会话恢复、资产隔离和 operation 重放。`cave.boundary_realm` 既有开放路径、奖励和战斗操作不受本合同影响。
