# v0.7 悬赏内容基线：道统起源服务

`docs/gameplay/adventures/content-v0.6.md` 冻结了 `bounty.dao_origin_service`：
「完成公共服务 3；12h；道统名望 +20、故事图鉴」。此前悬赏运行时只有四种进度口径
（`inventory_gain`、`production_completed`、`exploration_battle_wins`、`dispatch_successes`），
没有「公共服务完成数」，因此这条悬赏无处落地。

## 数据合同

`data/任务/悬赏.json` 新增一条记录（kind `bounty`）：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `required_realm` / `required_layer` | `dao_union` / 1 | 合道起 |
| `duration_seconds` | 43200 | 12 小时 |
| `daily_limit` | 1 | 每日一次 |
| `target_kind` | `public_service_completions` | 本版新增的进度口径 |
| `target_key` | `null` | 对**任意**公共项目完成服务即计入，故不需要固定项目键 |
| `target_amount` | 3 | 三个不同公共项目 |
| `reward_pool_key` | `reward_pool.bounty.void_anchoring` | 复用既有道统向奖励池 |
| `reputation_key` | `local.dao_service` | 道统名望 |

`target_key` 允许为空，与 `production_completed` 同等对待（校验器与运行时快照校验都按
`keyless_kinds` 处理），因此不需要编造 `project.dao_settlement` 这类仓内并不存在的项目键——
实装前实测公共项目只有 `project.town_well`、`project.market_road`、`project.herb_garden`、
`project.domain_refuge`、`project.abyss_purification`、`project.ancestral_habitat` 六个。

## 进度口径

`public_service_completions` 统计**接取之后**、`contribution_kind = 'service'` 的
**不同公共项目数**：

- 资源贡献不算服务（`contribution_kind = 'resource'` 被排除）。
- 同一项目重复服务只计一次（`COUNT(DISTINCT project_id)`）。
- 接取之前的历史服务不计入（窗口用 `created_at > accepted_at`，与 `dispatch_successes` 一致）。
  刻意不用「基线相减」：distinct 计数配基线在「接取后再次服务同一项目」时会算少，实测已暴露。

## 非目标

不改公共项目本身的贡献与结算规则、不改既有四条进度口径、不新增战斗或事件；
不改道统名望上限与其他悬赏的奖励池。
