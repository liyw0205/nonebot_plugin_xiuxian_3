# v0.9 社交内容基线：道侣终局协作

`docs/gameplay/social/content-v0.6.md` 冻结了 `partner.endgame_task`：「有效道侣、双方终局会话未锁」，
「共享协作任务，各得功勋；不改结局」，错误码 `ENDGAME_PARTNER_STATE_CONFLICT`。此前 `partner_*`
只有关系生命周期、`final_battle_members` 只记战斗贡献，二者之间没有协作任务层，本版补上。

## 数据合同

`data/社交/道侣协作.json`（kind `partner_task`，`task.partner.endgame.defaults`）：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `required_ending_state` | `open` | 双方都未写 `endgame_endings` 才能协作 |
| `window_days` | 7 | 任务时限（展示与快照口径） |
| `target_kind` | `endgame_assist_wins` | 进度来源限定为协作助战胜利 |
| `target_amount` | 1 | 达成 1 场即完成 |
| `reward_world_merit` | 20 | 双方各得（不是合计） |
| `reward_items` | `item.spirit_water ×1` | 普通材料白名单 |

奖励刻意压得很低：协作是「同行」而非「速成」，且世界功勋是终局资源，不能靠道侣任务刷取。
加载器把终局专属资产（`item.tribulation_token`、`item.ascension_certificate`、
`item.tribulation_guard`、`item.dao_fruit_fragment`、`item.domain_core`）列入**禁止发放**清单。

## 校验与迁移边界

`social/partner_task_content.py` 校验字段集合、正数、`required_ending_state` 与 `target_kind` 枚举、
奖励物品必须存在且不在禁止清单、数量为正、别名非空；非法抛 `ContentError` 并在导入期构建。
新增两表 `partner_tasks`、`partner_task_claims`（`UNIQUE(task_id, player_id)` 保证每人只领一次），
`CREATE TABLE IF NOT EXISTS`，旧库无需迁移。

## 运行时

- **进度**由既有表派生，不新增计数：统计该关系双方在任务创建后、`status IN ('won','settled')`
  的终局战中作为 `helper` 的场次。任务自己不能写进度。
- **发起**：需活跃道侣关系；同一关系同时只允许一个 `open` 任务（`PARTNER_TASK_ACTIVE`）；
  任一方已写结局则 `ENDGAME_PARTNER_STATE_CONFLICT`。
- **领取**：达成后双方**各自**领取一次 `reward_items` + `reward_world_merit`
  （`world_merit` 走玩家数值而非背包，避免被当成物品）；两侧都领取后任务转 `completed`。
  重复领取返回 `PARTNER_TASK_CLAIMED`（重放同一 operation 幂等返回原结果）。
- 任务**不写** `endgame_endings`，不改 `ascension_merit`、天劫债、道果进度。

## 命令与呈现

`道侣协作`（别名 `道侣终局协作`）、`开始道侣协作`、`领取道侣协作`。
错误码：`PARTNER_TASK_NO_PARTNER`、`PARTNER_TASK_ACTIVE`、`PARTNER_TASK_NOT_COMPLETE`、
`PARTNER_TASK_CLAIMED`、`ENDGAME_PARTNER_STATE_CONFLICT`、`INVALID_PARTNER_TASK_COMMAND`、
`LEDGER_CONFLICT`，失败零写。状态页按状态只挂一个按钮（未开始→开始、可领→领取），
QQ 原生 Markdown 附蓝字预填；OneBot/纯文本降级为可读命令；`修仙帮助 社交` 追加段。

## 非目标

不做跨服配对、不做玩家间资产转移、不新增战斗、不下调/上调既有终局战奖励；
不把协作结果写回任何一方的 `ending_state`。
