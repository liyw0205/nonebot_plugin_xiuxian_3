# v0.6 境界内容基线：合道、渡劫与终局

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。v0.6 的终局结算不可用普通突破替代，所有选择由长期状态、三次试炼与最终战共同决定。

本文件是 `content-0.6` 的历史发布快照，不裁决当前运行时状态。当前代码状态以
[当前开发状态](../../current-status.md) 和战斗域的自动回合合同为准；快照中的数值、稳定键和
终局前置仍是实现必须引用的内容基线。

- `content_version`：`content-0.6`
- `rule_version`：`progression-0.6.0`
- 正式开放：`dao_union`（合道）、`tribulation`（渡劫）、`ascension_ready`（飞升候选）。两境均使用 L1–L10，阈值和段位以[十层规范](layers.md)为准。
- 写用例：`progression.begin_dao_union`、`tribulation.start_trial`、`tribulation.settle_trial`、`ascension.choose_ending`。

## 1. 终局状态机

```text
void_refining/L10 混元
  -> dao_union/L1
  -> dao_union/L9 圆满（前置试炼）
  -> dao_union/L10 混元（渡劫入境）
  -> tribulation/L1 -> L3 -> trial_1 -> L6 -> trial_2 -> L9 -> trial_3 -> L10 混元
  -> final_battle
  -> ascension_ready
  -> ascend | remain_in_world
```

中途失败不降至炼虚以下。每一阶段的 `operation_id` 与试炼轮次一起组成唯一键；相同 operation 重放原试炼结果，不重新抽取天劫。

## 2. 合道：`progression.begin_dao_union`

| 前置 | 成本 | 成功产出 | 失败/拒绝 |
|:--|:--|:--|:--|
| 炼虚 L10 混元、总修为 `>=2,998,960`、完成 `quest.dao_union`、至少一条道途终局任务完成 | `item.dao_fruit_fragment` 10、世界功勋 2,000、灵石 300,000 | `dao_union` L1、`resource.dao_fruit_progress=0`、三个可选道果线索 | 前置不足不扣；合道不采用随机失败 |

`quest.dao_union` 要求：完成一条三界主线、贡献一次跨服宗门战或等价个人挑战、交付一种本职业终局作品。它的检查快照必须保存，以免赛季条件更新后破坏历史资格。

合道层数 L1–L10 门槛见 `layers.md`。合道 L9 只开放天劫预览；L10 混元满足任务/资源后进入渡劫 L1。渡劫可通过普通修为从 L1 晋至 L3；之后每次正式试炼打开下一段层数。天劫资格由层数、试炼与资源共同决定，不由无限刷修为获得。

## 3. 三次天劫试炼

| 试炼键 | 开放条件 | 成本 | 固定奖励 | 失败后果 |
|:--|:--|:--|:--|:--|
| `trial.body_and_mind` | 渡劫 L3 | `item.tribulation_token` 1 | 开放渡劫 L4–L6；道果进度 100；`resource.ascension_merit` 100；`item.dao_fruit_fragment` 1 | `resource.tribulation_debt +10`，24 小时不可重试 |
| `trial.three_realms` | 第一次成功、渡劫 L6 | `item.tribulation_token` 1、三界声望各 2,000 | 开放渡劫 L7–L9；道果进度 180；`resource.ascension_merit` 200；世界功勋 500 | 债务 +15，48 小时不可重试 |
| `trial.dao_choice` | 前两次成功、渡劫 L9、道果进度 `>=280` | `item.tribulation_token` 1、选择对应 `fruit_key` | 锁定候选道果；道果进度 250；`resource.ascension_merit` 250 | 债务 +20，72 小时不可重试 |

三次试炼和三项道源任务的固定奖励合计为道果进度 1,000、`resource.ascension_merit` 1,000。`trial.three_realms` 另给世界功勋 500；道源任务另给世界功勋共 1,000。债务达到 100 时，下一次试炼追加 `difficulty_bp=2000`，表现为敌方护盾/环境机制，不能直接扣除角色资产。

三次试炼只能在 `tribulation.sky_terrace` 启动；从 `dao.origin_gate` 前往天劫台的移动另消耗 1 张天劫凭证，不替代每次试炼自身的凭证成本。原始 v0.6 规则曾以确定性检定描述试炼；当前运行时已将试炼接入共享服务端自动回合 `BattleSession`，客户端仍不能提交技能、目标、伤害或结果。最终战仍未开放。

## 4. 最终战与飞升候选

第三次试炼成功后，三项道源任务补足道果/功勋并开放渡劫 L10；`progression.advance_layer` 仍必须逐层结算，不能直接跳过 L10。`tribulation.final_battle` 前置：渡劫 L10、三次试炼成功、`resource.dao_fruit_progress>=1,000`、`resource.ascension_merit>=1,000`、`resource.tribulation_debt<100`。成本：`item.ascension_certificate` 1；会话锁 30 分钟；队伍最多 5 人，只有发起者结算终局，协助者按贡献获得绑定世界功勋。

成功：状态改为 `ascension_ready`、发放 `item.title.ascended`、生成可选择的 `ascension.ending.<player_id>` 记录；失败：保留所有试炼进度，`tribulation_debt +25`，7 天内不可再次发起最终战。最终战失败不消耗 `item.ascension_certificate`，但尝试记录永久保留。

## 5. 终局选择：`ascension.choose_ending`

| `ending_key` | 前置 | 结果 | 不可逆边界 |
|:--|:--|:--|:--|
| `ascend` | `ascension_ready`、最终战成功 | 角色进入终局角色表；核心资产冻结；开启新篇章入口 | 不能返回普通三界经济/排行 |
| `remain_in_world` | `ascension_ready`、拥有已锁定 `fruit_key` | 进入留界道统表；保留道果与展示称号，不能再次飞升 | 不生成飞升凭证或再次结局奖励 |

每条首要道途的 `fruit_key` 在 `foundation/paths/content-v0.6.md` 定义。选择结果同时写角色终局状态、道果、赛季历史和 operation；重复请求返回同一结局。

## 6. 错误、回滚与验收

- 错误：`DAO_UNION_REQUIREMENT_MISSING`、`TRIAL_SEQUENCE_INVALID`、`TRIBULATION_COOLDOWN`、`TRIBULATION_DEBT_BLOCKED`、`ASCENSION_REQUIREMENT_MISSING`、`ENDING_ALREADY_CHOSEN`。
- 关闭：停止新合道、试炼和最终战；已创建会话按原版本结算，`ascension_ready` 玩家仍可完成一次结局选择。
- 回滚：终局前创建赛季快照；恢复不得把已选择 `ascend`/`remain_in_world` 的角色重新投入普通经济。若恢复中断，状态为 `ending_pending_recovery`，仅管理员恢复用例可继续。
- 验收：试炼顺序不能跳过；失败债务和冷却只结算一次；协助者不取得发起者境界；两种结局互斥且重试稳定；关闭后不新建会话、不丢弃旧会话。
