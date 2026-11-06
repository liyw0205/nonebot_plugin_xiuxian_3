# v0.11 飞升路线试炼进度加成

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.11`，
`rule_version=social-0.11.0`。本版把 `content-v0.8.md` 记录在案的后续项接上：渡劫试炼结算读取
玩家宗门的 `dao_route_state`，飞升路线按既有加成把道果进度奖励提高 10%。本版不改任何 `data/`
文件，也不新增内容键。

## 1. 内容与数值

`data/社交/道统路线.json` 的 `route.dao_settlement.ascend` 已带
`bonus.dao_fruit_trial_bonus_bp=1000`（与 v0.8 冻结值一致，上限 3000 bp 由加载器校验）。
试炼奖励本身仍来自 `data/事件/事件.json` 的 `event.heaven_tribulation.trials`：

| 试炼 | key | `progress_reward` | 飞升路线实际进度 |
|:--|:--|--:|--:|
| 身心劫 | `trial.body_and_mind` | 100 | 110 |
| 三界劫 | `trial.three_realms` | 180 | 198 |
| 道果劫 | `trial.dao_choice` | 250 | 275 |

有效进度 = `progress_reward * (10000 + dao_fruit_trial_bonus_bp) // 10000`。数值只从路线内容读取，
试炼代码不复制 1000；路线内容缺失、加成键不匹配或数值非法时按 0 bp 处理，不阻断结算。

## 2. 结算流程

`settle_tribulation_trial` 在读取战斗结果并确认 `won` 后：

1. 读取玩家当前活跃宗门与 `dao_route_state.route_key`；
2. 仅当路线为 `route.dao_settlement.ascend` 时读取该路线的
   `dao_fruit_trial_bonus_bp`；
3. 计算有效进度并随既有 `grant_player_state` 事务写入 `dao_fruit_progress`；
4. 结果与 `operations` 载荷新增 `base_progress_reward`、`route_bonus_bp`、`reward_progress`；
5. 失败试炼的 `base_progress_reward`、`route_bonus_bp`、`reward_progress` 均为 0。

加成在结算时按当时路线计算，开始试炼与战斗预览不冻结。路线在战斗期间变更时以结算时为准，
`route_bonus_bp` 保留本次实际使用的 bp 供审计。预览、战斗绑定、冷却、债务、道果选择与
`operations` 回放语义不变。

## 3. 上限与实际增量

`dao_fruit_progress` 上限仍为 1300。`reward_progress` 是本次实际写入的增量：

- 未触顶：等于有效进度（例如 100 + 10% = 110）；
- 触顶：等于剩余空间（例如已有 1290 时，110 只落地 10），结果仍保留
  `base_progress_reward=100`、`route_bonus_bp=1000` 与计算值供呈现；
- 触顶时没有负增量，也没有把超出部分转入其它资源。

## 4. 呈现与兼容

`渡劫试炼` 结算回执在进度行显示来源，例如
`道果进度 +110（基础 100 + 飞升路线 10% = 110）`；触顶时追加
`，已达道果进度上限`。无加成（无宗门、无路线、非飞升路线或试炼失败）时不显示括号段，
回执与旧版一致。百分比由 bp 换算，不在文案里另写常量。不新增命令、按钮或帮助段；
`修仙帮助 修炼` 的既有试炼段不变。

- 结果新增字段只进入 `operations` 与试炼结果载荷，`tribulation_trials`、战斗表与快照结构不变。
- 旧 operation 结果缺 `base_progress_reward` / `route_bonus_bp` 时按 0 回放，不改写已结算进度。
- 相同 operation 回放返回首次结果，不重复计算加成或重复加进度；重启后结果与进度保持。
- 不改变道果选择、道果碎片、飞升资格、债务或冷却。

## 5. 错误与边界

不新增错误码。无活跃宗门、宗门无 `dao_route_state`、路线非飞升、路线内容缺失或
`bonus.value_bp` 非法时均按 0 bp 结算。若未来路线内容被移除，已结算结果不回算。

## 6. 验收

`test/test_tribulation_endgame_chain.py` 覆盖：

- 飞升路线成功结算：`base_progress_reward=100`、`route_bonus_bp=1000`、
  `reward_progress=110`、`dao_fruit_progress` 280→390，回执含
  `基础 100 + 飞升路线 10% = 110`；
- 无宗门、宗门无路线、守界/留界路线：0 bp，进度仍 280→380，回执无加成段；
- 开始试炼后才加入飞升宗门：结算时读取到 1000 bp；
- 失败试炼：0 bp、进度不变、回执无加成段；
- 1290 触顶：实际增量 10、落地 1300，回执标注已达上限；
- 相同 operation 回放与进程重启：结果字段与进度都不重复累计；
- 旧结算载荷缺新字段：按 0 bp 回放，`reward_progress` 保持原值。

回归：`test_tribulation_endgame_chain.py`、`test_tribulation_combat.py`、
`test_tribulation_content.py`、`test_dao_route.py`、`test_content.py`、
`test_m9_content_integrity.py`、`test_documentation.py`。
