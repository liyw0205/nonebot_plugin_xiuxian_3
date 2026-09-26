# v0.1 境界内容基线：凡人至筑基十层

本文件遵守 [版本内容开发合同](../../content-development-contract.md) 和[境界十层与段位规范](layers.md)。

- `content_version`：`content-0.1`
- `rule_version`：`progression-0.1.1`（调息）；`progression-0.1.2`（灵泉）；`progression-0.1.3`（聚气突破）；`progression-0.1.4`（历史筑基突破）；`progression-0.1.5`（静修）；`progression-0.1.6`（筑基道基质量来源）
- 开放写用例：`progression.start_cultivation`、`progression.settle_cultivation`、`progression.advance_layer`、`progression.breakthrough_qi_gathering`、`progression.breakthrough_foundation`、`progression.recover_weakness`。
- 角色在 `player.enter_cultivation` 成功后进入 `qi_sensing` L1（感气一层/入门）；`mortal` 没有修为资产，不能创建修炼或突破 operation。

本文件是 `content-0.1` 的历史开放快照。首版完整范围、境界路线和跨域依赖以[完整内容开发总表](../../content-development.md)为准；十层的阈值、段位推导和迁移语义以 `layers.md` 为公式权威。若与总表冲突，先修总表，再生成新的快照。

## 1. 首版开放境界

| `realm_key` | 名称 | 可用层数 | 跨境条件 | 解锁方向 |
|:--|:--|:--|:--|:--|
| `mortal` | 凡人 | 0 | 完成入道后进入感气 L1 | 新手城、采集、打工、居所、灵田、城镇委托、基础交易 |
| `qi_sensing` | 感气 | L1–L10 | L10 混元 + 总修为 >=1,360 | 修炼、基础功法、近郊战斗、常驻经营 |
| `qi_gathering` | 聚气 | L1–L10 | L10 混元 + 总修为 >=4,260 | 基础装备、炼丹/炼器/布阵、宗门申请、洞天入口 |
| `foundation` | 筑基 | L1–L10 | v0.1 只开放成长；金丹突破为 `closed` | 雾隐洞天一层、正式悬赏、宗门贡献、基础 PVE |
| `golden_core` | 金丹 | `placeholder` | v0.2 才开放 | 不得作 v0.1 前置/奖励/地点结果 |
| `nascent_soul` | 元婴 | `placeholder` | v0.3 才开放 | 不得作 v0.1 前置/奖励/地点结果 |

展示段位由层数推导：L1–L3 入门、L4–L6 稳固、L7–L9 圆满、L10 混元。L9 仍是圆满而非跨境资格；只有 L10 可以创建跨境突破会话。

### 首版层数门槛

| `realm_key` | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 | L9 | L10 混元 |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `qi_sensing` | 0 | 80 | 170 | 280 | 410 | 560 | 730 | 920 | 1130 | 1360 |
| `qi_gathering` | 0 | 180 | 380 | 620 | 900 | 1220 | 1580 | 1980 | 2420 | 2900 |
| `foundation` | 0 | 420 | 900 | 1480 | 2180 | 3000 | 3950 | 5050 | 6300 | 7700 |

## 2. 修炼会话：`progression.start_cultivation`

| `mode_key` | 前置 | 费用 | 持续时间 | 基础修为 | 冷却/次数 |
|:--|:--|:--|:--|--:|:--|
| `cultivate.breathing` | 感气 L1 以上、地点允许 | 2 体力 | 10 分钟 | 40 | 每角色同时 1 个 |
| `cultivate.spirit_spring` | 感气 L2、完成教学采集、位于 `xuantian.spirit_field` | 3 体力 | 15 分钟 | 70 | 每日 4 次 |
| `cultivate.seclusion` | 聚气 L1、无队伍/战斗/生产锁 | 6 体力、2 精力 | 30 分钟 | 170 | 每日 2 次 |

开始时冻结角色、`realm_key`、`realm_layer`、悟性、地点环境、道途、功法、状态、体力/精力、`rule_version`。结算公式：`floor(base_exp * training_rate_bp * environment_bp * state_bp / 1000000000000)`；倍率均为 bp，默认环境/状态为 10000。修炼没有随机池；结果只由已保存快照决定。

结算先增加 `realm_cultivation` 和 `total_cultivation`，再只读计算可晋层的最高下一层；不会自动跳层。`progression.advance_layer` 必须使用独立 operation 逐层结算，确保 L3/L6/L9/L10 的内容解锁可审计。

会话状态：`created -> running -> settled | cancelled | expired`。未到结束时间返回 `CULTIVATION_NOT_READY`；超过结束时间 24 小时可由恢复任务按原快照结算。当前最小实现允许 `running` 阶段取消并返还已锁定体力；重复 operation/结算返回同一会话与结果。

当前运行时开放 `cultivate.breathing`、`cultivate.spirit_spring` 和 `cultivate.seclusion` 的
`running -> settled/cancelled/expired` 最小实现。调息使用 `开始修炼`，灵泉使用
`开始修炼 灵泉`；两者都支持 `结算修炼`、`恢复修炼` 和 `取消修炼`。调息开始时扣除
2 点体力并冻结悟性、境界、地点和规则版本，10 分钟后才能结算；灵泉要求感气二层、
完成 `guide.gather_blood_grass` 且位于 `xuantian.spirit_field`，开始时扣除 3 点体力，
持续 15 分钟，基础修为 70，使用 11500 bp 环境倍率，每日最多 4 次。结束后 24 小时内
允许普通结算，超过窗口标记为 `expired`，只能由 `恢复修炼` 按原快照完成一次迟到结算；
相同 operation 回放原结果，不同 operation 也不能重复增加修为。取消会原子返还对应模式
的体力。修为收益写入境内修为与总修为，随后由 `晋升境界` 独立 operation 逐层推进。
静修使用 `开始修炼 静修`，要求聚气一层且没有队伍、战斗或生产锁；开始时原子扣除 6 点体力和 2 点精力，持续 30 分钟，基础修为 170，每日最多 2 次。静修取消时按开始快照返还体力和精力；结算同样只增加修为，不会自动晋层。

聚气突破已接入最小运行时闭环：感气 L10 混元、总修为至少 1,360，且未处于修炼、生产或
虚弱状态时，可发送 `突破预览 聚气` 查看条件，再发送 `开始突破 聚气`（可追加 `护脉`）创建
3 分钟会话。开始时原子扣除焦点丹 ×1、灵叶 ×3 和 100 灵石，并冻结地点、道途、资质、
规则版本、随机池和保底；结算使用开始时快照，成功率基础为 8,000 bp，失败保底每次增加
300 bp，最多增加 900 bp。成功进入聚气 L1，境内修为归零，奖励灵石 80、体力 5；失败
保留感气境内修为 80%，进入虚弱 2 小时。聚气护脉丹不提高成功率，只在失败时消耗，改为
保留 90% 修为并将虚弱缩短到 30 分钟。发送 `恢复虚弱` 可在到期后恢复，`恢复虚弱 提前`
消耗低阶疗伤丹 ×1 和 50 灵石；恢复不会清除失败保底。重复 operation 只回放原结果，结算
期间不会重复扣费、发奖或重抽随机结果。

筑基突破已接入同一突破会话框架：聚气 L10 混元、总修为至少 4,260 时，可发送 `突破预览 筑基`
和 `开始突破 筑基`，会话持续 5 分钟。开始时扣除筑基丹 ×1、阵砂 ×3、铁石 ×3 和 500
灵石；基础成功率 7,500 bp，道基质量按 `foundation_quality // 10` 加成（最多 1,000 bp），
匹配功法与阵法辅修各可加 300 bp，最终不超过 9,000 bp。成功进入筑基 L1，奖励世界功勋
50 与雾隐洞天一层凭证，并将道基质量确立为原值与 5,500 的较大值；该值在开始快照中冻结，
`rule_version=progression-0.1.6`。失败不提高道基质量，保留聚气修为 70%，虚弱 6 小时。筑基护脉丹只在失败时消耗，
保留 85% 修为并将虚弱缩短到 2 小时；失败保底每次增加 400 bp，最多 +1,200 bp。历史
会话按快照结算，金丹突破仍为 `CONTENT_CLOSED`。

## 3. 同境晋层：`progression.advance_layer`

输入：`player_id`、目标层数（只能是当前层 +1）、`operation_id`。前置：active、无互斥会话、当前 `realm_cultivation` 达到层数阈值。成功仅改 `realm_layer` 和派生显示段位，不消耗材料、不随机、不扣修为。

| 层数 | 段位 | 首版解锁 |
|:--|:--|:--|
| L3 | 入门完成 | 道途指导、常驻经营第二类服务预览 |
| L6 | 稳固完成 | `cultivate.seclusion`（聚气以上）、宗门常规任务资格 |
| L9 | 圆满 | 突破预览、精英/洞天准备提示；不能突破 |
| L10 | 混元 | 对应跨境突破可预览；只有满足所有材料/总修为/状态时才可开始 |

相同 operation 回放同一层数；目标非下一层、阈值不足或 L10 后再晋层返回 `REALM_LAYER_INVALID` 或 `REALM_CULTIVATION_INSUFFICIENT`，不改资产。

## 4. 聚气与筑基突破

| 目标 | `operation_type` | 必需材料/资源 | 基础成功率 | 准备加成 | 最终范围 |
|:--|:--|:--|--:|:--|:--|
| `qi_gathering` | `progression.breakthrough_qi_gathering` | `item.pill.focus_low` 1、`item.herb.spirit_leaf` 3、灵石 100 | 8,000 bp | 匹配灵根地点 +500 bp、宗门引导 +300 bp | 8,000–9,000 bp |
| `foundation` | `progression.breakthrough_foundation` | `item.pill.foundation_draft` 1、`item.mat.array_sand` 3、`item.ore.ironstone` 3、灵石 500 | 7,500 bp | 道基质量 `//10`（最多 1,000 bp）、匹配功法 +300 bp、阵法辅助 +300 bp | 7,500–9,000 bp |

两种突破都要求当前境界 L10 混元、总修为达到上表门槛、`status=active`、未处于战斗/生产/移动/修炼/虚弱；会话锁分别为 3 分钟与 5 分钟。开始时冻结 L10 属性、道途、功法、地点、材料、辅助项与 `random_pool=breakthrough.<target>.v0.1`。仅 `roll_bp < success_bp` 成功；相同 operation 永远回放同一 `roll_bp`。

| 结果 | 聚气 | 筑基 |
|:--|:--|:--|
| 成功 | 进入 `qi_gathering` L1；`realm_cultivation=0`；发 `progression.reward.qi_gathering_entry`：灵石 80、体力 5 | 进入 `foundation` L1；`realm_cultivation=0`；发 `progression.reward.foundation_entry`：世界功勋 50、`item.cave_pass_basic` 1 |
| 失败（无保护） | 消耗材料/灵石；感气 `realm_cultivation` 保留 80%；`weakness` 2h；下次 +300 bp，最多 +900 bp | 消耗材料/灵石；聚气修为保留 70%；`weakness` 6h；下次 +400 bp，最多 +1,200 bp |
| 失败（保护） | `item.pill.qi_guard` 仅失败时消耗；修为保留 90%，虚弱 30m | `item.pill.foundation_guard` 仅失败时消耗；修为保留 85%，虚弱 2h |

失败后修为夹断为 `0..L10 threshold`，层数保持 L10；不降境、不删除道途/物品/地点。`weakness` 期间普通修炼收益 -2000 bp，拒绝新突破与雾隐洞天；到期自动恢复，或消耗疗伤丹 1、灵石 50 提前恢复。提前恢复不清除失败保底。

## 5. 失败、权限、关闭与验收

错误：`REALM_MISMATCH`、`REALM_LAYER_INSUFFICIENT`、`REALM_LAYER_INVALID`、`REALM_CULTIVATION_INSUFFICIENT`、`CULTIVATION_INSUFFICIENT`、`BREAKTHROUGH_BUSY`、`WEAKNESS_ACTIVE`、`MATERIAL_INSUFFICIENT`、`BREAKTHROUGH_LOCATION_FORBIDDEN`、`CONTENT_CLOSED`。角色本人可创建；管理员只能读取快照或执行独立恢复用例。

记录：旧/新境界和层数、段位派生值、总/境内修为、success/roll bp、保底前后、材料/保护丹、虚弱期限、内容/规则版本和来源快照。关闭 v0.1 时不建新会话；已 `preparing` 的会话按原版本完成或在未扣成本时取消。恢复不得重抽突破随机或双发奖励。

验收：凡人不能修炼；L1–L10 阈值逐层正确；L9 不可突破而 L10 可预览；地点/材料/资源不足无变化；运行中会话不重复创建；保护丹不提高概率；失败保留比例准确且只应用一次；文本和按钮共用 application 用例；历史会话仍按 `progression-0.1.1` 结算。

首版不开放金丹、元婴、化神、炼虚、合道、渡劫和飞升的可执行内容。
