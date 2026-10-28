# 当前开发状态

本文是当前工作队列、运行状态、发布进度和验收证据的唯一入口。更新日期：2026-10-17。
产品范围与规则见[完整内容开发总表](content-development.md)和领域合同；工程规则见
[开发指南](development-guide.md)，测试触发条件见[测试策略](testing.md)。
不得从历史切片、JSON 已存在或测试夹具推断玩家已可执行。

分支职责固定为：`main` 是安装/Release 分支，只有验证通过的普通合并结果才进入；`develop`
是唯一活动开发分支。旧 `work/*`、`docs/*` 分支和 worktree 仅作历史保留，不删除、不盲合。
正式 Release、指定实例部署、真实 QQ 连接和 QQ 富消息呈现分别记录，不能互相替代。

## 1. 状态与完成判定

| 状态 | 含义 |
|:--|:--|
| `open` | 既有入口、application、持久化、幂等和相应适配器验收已接入 |
| `partial` | 仅部分声明的能力闭合；可修补既有路径，不扩大入口 |
| `contract` | 合同已闭合但运行时尚未接入 |
| `locked` | 已登记但前置不满足；拒绝新建，不扣资产 |
| `planned` | 规则未闭合；先列具体问题，不创建会话 |
| 工作项 `blocked` | 缺明确规则、依赖或外部验证条件；记录所需输入与解除条件 |

开放状态描述实现，不代替本次发布验收。历史验收、当前定向通过、全量通过、真实平台通过
分别记录；单项完成、没有新小缺陷或存在跳过测试不能证明本轮全部必需工作或完整游戏完成。

## 2. 当前已接入能力

以下为已有实现摘要，不重新定义数值。完整停止时记录见
[状态历史归档](current-status-history-2026-10-09.md)，领域实现合同仍保留在原目录。

| 玩家功能域 | 已接入范围 | 尚不能由此推断 |
|:--|:--|:--|
| 角色与境界 | 创建、寻仙、凡人引导、入道、资料；九个修仙境界各十层、突破/恢复；公开命令链已有渡劫 L10 与飞升结局历史证据 | 当前改动后的完整成长长链、真实平台重新验收 |
| 道途与构筑 | 六大道途、五种可选辅修、18 功法及其来源、体质、技能、装备与祭炼/重铸；配置、开始快照与自动战斗消费；采矿/烹饪与基础灵具来源已补齐 | 刻意锁定效果已经消费，或当前树无夹具完整成长已重新通过 |
| 世界、探索、冒险 | 玄天/三界/虚空/终局移动、采集探索悬赏、已有秘境/遗府及主线；矿区已有许可/矿镐/采矿公开准入来源 | 未来新地图、副本与刻意锁定内容已经开放 |
| 战斗 | 服务端自动单人/多人 PvE、个人竞技与 2v2/3v3/2v3 PvP、终局战、回放/恢复；训练傀儡和直接切磋只读观战 | 跨服匹配、客户端提交行动或结果 |
| 生产与生活 | 个人生产、设施、契约、居所灵田、委托服务、短运、公共建设和终局配方 | 仅新增 JSON 即可开放所有新配方 |
| 经济与社交 | 固定市集、求购、拍卖、生产委托；宗门、师徒/道侣、队伍、堡垒/本地宗门周赛、信标/联盟 | 跨服身份合并、玩家资产转移、复杂市场与跨服交易 |
| 活动与道历 | 灵泉/三界/领域/虚空/终局活动赛季、问安补录、七日、派遣、机缘、道契测试权益、问道行卷 | 外部正式支付和未定义世界事件 |
| 灵兽与特色 | 灵兽/灵骑成长、出战/运输快照；雾隐塔 1–45、三界塔单人/双人 1–40、虚空塔单人 1–90、图鉴/剧情 | 未定义品种、配方、剧情或分享授权 |
| 适配器与工程 | QQ/OneBot 共用 application、消息降级、SQLite/UoW/ledger、随机/恢复、安装与备份 | 真实账号设备与正式发布/P7 外部接入已经验收 |

锁定范围仍包括器灵召唤/御兽亲和等未消费效果、无完整合同的后续内容、Web 写操作、
正式支付、跨服匹配/身份合并/资产转移。它们仍在完整产品范围对照中，须标明合同或条件
缺口，不自动删除、视为完成或开放。

## 3. 冻结的完整游戏发布目标

以下保留 M5/M9 的历史冻结范围，不是重新开发或重跑验收的授权；当前有限任务及完成结果仅由第 4 节裁决。

本轮范围是 `content-development.md` 第 3–5 节的全部境界和功能域及现行领域合同，
包含完整成长到飞升/留界、六道途构筑、来源/内容消费、世界探索战斗、生产生活经济社交、
活动道历灵兽、既有副本塔剧情，以及安装、运维、恢复、QQ/OneBot 与发布验收。
MVP-1 与 v0.1–v0.6 是内容/历史边界，不把本轮目标缩成新手片段或回放修补。

先在下方有限队列补出各域明确缺项，冻结依赖与验收标准，再逐项交付。范围变更须说明
来自哪条现行合同或明确需求；不得因完成一个小片段而提前结束，也不得为维持开发循环
不断追加无证据的“下一缺陷”。M3 结束时冻结明确的本地必需任务表，后续不自动扩大本轮范围。
合同不足时列出能回答的规则问题和解除条件，保留阻塞，不等待无变化条件反复扫描。
完整产品范围继续保留；2026-10-10 本地 M5 goal 已完成验收、审查和提交推送。
M6 首采集与 QQ 配置以及分类帮助/悬赏蓝字已完成。用户新授权 M7：补齐既有玩法的缺失本地
数据/来源/配方，可由 xiu3 保守设计并记录规则；不再要求用户逐个提供普通来源数值。
刻意锁定的未来内容、B2 平台条件、B3 发布/环境仍独立，不因本地补全自动开放。
短 goal 见[开发指南](development-guide.md#可复用-goal)。

## 4. 唯一工作队列

**M9 全部既有本地功能的内容定义、来源/引用闭合与受影响消费者已完成并合入 `main`；合并提交为 `9be1cae`，收口文档随后已普通推送。**
M7 仅证明旧范围的最小来源/引用接线，不证明内容完整；M8 交互已独立推送并保留。
分支已普通推送并正常合并到 `main`；Quality and Release 工作流 `38108888614` 已成功。
此处是 M9 历史结果；后续 v0.1.1–v0.1.4 已正式发布，B2/B3 的消息呈现、支付和跨服条件仍单列。
B1 刻意锁定未来内容、B2 真实平台、B3 发布/支付/跨服条件独立保留。
M5 最终当前树本地阶段验收、审查与提交推送已完成；保留已收口的 M1/M2 与冻结的 M3
对照结论；不重新全域扫描或自动扩大业务范围。
主线更新本表；切片详情只在对应行说明，不再向实施计划或本文追加重复历史账本。

主线剧情与离线成长首个真实纵向切片已推送 `42d1772`；不扩成 84 条主线批量填充，
不重做 M9 数据，不把现存 PvP 入口描述成完整开放世界竞技生态。

`chapter.2.stage.2` 云城初见内容化切片已在 `develop` 完成：正文、`travel_arrival`
目标（结算后的公开抵达 `xuantian.cloud_city`）、行动、首通状态事件、`next_stage_key`
指向 `chapter.2.stage.3` 与失败重试规则均已落地，沿用现有 objective 消费者与
快照/事务/幂等语义，阶段列入内容化校验集合。关卡境界要求由旧的 `foundation` L1
对齐为可达路线实际要求的 `golden_core` L1：区域通路、地点 JSON 与 travel 校验
都以结丹一层为云城门槛，story 声明与可达性不静默放宽世界准入。
`chapter.2.stage.3` 商会听潮内容化切片已随后在 `develop` 完成：正文、`travel_arrival`
目标（结算后的公开抵达 `xuantian.floating_boat`，含五百灵石渡资的既有行程成本）、
行动、首通状态事件、`next_stage_key` 指向 `chapter.3.stage.1` 与失败重试规则均已
落地，境界门槛保持既有 `foundation` L1，与渡口路线要求一致。
`chapter.3.stage.1` 云铁入山内容化切片已随后在 `develop` 完成：正文、`travel_arrival`
目标（结算后的公开抵达 `xuantian.cloud_mine`，公开来源地点云城/青石镇、既有筑基
四层门槛不变）、行动、首通状态事件、`next_stage_key` 指向 `chapter.3.stage.2`
与失败重试规则均已落地；`chapter.3.stage.2` 矿兽试锋内容化切片已随后在 `develop`
完成：正文、`exploration_reward` 目标（结算后的公开 `explore.cloud_mine` 采掘取得
云铁 ≥1，既有许可/矿镐/采矿辅修 access_any 准入与筑基六层门槛不变）、行动、首通
状态事件、`next_stage_key` 指向 `chapter.3.stage.3` 与失败重试规则均已落地；
`chapter.3.stage.3` 云舟试航内容化切片已随后在 `develop` 完成：正文、
`exploration_reward` 目标（结算后的公开 `explore.cloud_boat_trial` 试炼取得试航签
≥1，既有结丹一层门槛、渡资与每日次数不变，回归路线矿区→青石镇→云城→渡口全部
为既有通路）、行动、首通状态事件、`next_stage_key` 指向 `chapter.4.stage.1` 与
失败重试规则均已落地；`chapter.4.stage.1` 阵堂初会内容化切片已随后在 `develop`
完成：正文、`travel_arrival` 目标（结算后的公开抵达 `xuantian.array_hall`，公开
来源地点云城/宗门山门、既有结丹一层门槛不变；阵堂研习门禁与旁观初会分离，本关
只要求抵达）、行动、首通状态事件、`next_stage_key` 指向 `chapter.4.stage.2` 与
失败重试规则均已落地；`chapter.4.stage.2` 阵纹试炼内容化切片已在 `develop` 完成：
正文、`exploration_reward` 目标（结算后的公开 `explore.gather_basalt_pass` 采掘
取得阵砂 ≥1，公开通路 阵堂→宗门山门→青石镇→近郊→玄武岩径、既有门槛/次数/成本
不变）、行动、首通状态事件、`next_stage_key` 指向 `chapter.4.stage.3` 与失败重试
规则均已落地；`chapter.4.stage.3` 玄天新章内容化切片已随后在 `develop` 完成：
作为玄天主线当前收录的收尾关，正文、`travel_arrival` 目标（结算后沿公开通路
玄武岩径→近郊→青石镇回镇合卷）、行动、首通状态事件与失败重试规则均已落地，
`next_stage_key` 如实留空；校验器改为数据驱动——内容化关卡必须前链，仅本故事
收录的最后一关可无后继，并由专项测试钉住两端。玄天 12 关内容化阶段至此完成；
后续卷章（航路/界壁/洞天各线）仍按题录保持未内容化，未批量展开。
数据改动为 `fd73925`/`b6ffef2`/`71f6a56`/`9c612ae`/`27a5de8`/`8a0b43f`/`e9efe27`
与 `3496a13`（ch4.stage.3）；官方 `剧情/主线.json`
各版 SHA-256 与 Git provenance 已登记 `scripts/seed_migrations.json`，聚焦组
`test_mainline.py`、`test_mainline_content.py`、`test_mainline_vertical_slice.py`
21 passed，`test_seed_migration.py` 7 passed（迁移测试覆盖旧官方 blob 升级、
重复升级幂等、用户自定义保留与回退），未重跑全量/压测。

`domain_frontier.guard.1` 烽火初燃内容化切片已在 `develop` 完成（数据提交 `f1cc95e`）：
正文、`travel_arrival` 目标（结算后的公开抵达 `xuantian.domain_front`，青石镇↔领域前线既有
通路）、行动、首通状态事件、`next_stage_key` 指向 `domain_frontier.guard.2` 与失败重试规则
（keep_running/0 秒）均已落地，该关列入内容化校验集合；官方 `剧情/主线.json` 新旧 SHA-256
与 Git provenance 已登记 `scripts/seed_migrations.json`，迁移测试反向助手只回退本关增量。
同时修复部署验载的校验覆盖缺口：`mainline.py` 导入期此前只解析 `story.mainline.xuantian`
一个故事，保留的自定义/未知主线若只在其他故事（本关所属 `story.mainline.domain_frontier`）
缺正文，部署会误判成功（returncode 0）而不回退；现导入期解析全部故事，部署验载同时显式
校验玄天/领域前线/虚空档案三个已收录故事，冲突种子在插件加载或验载即失败并回退源码、
TOML 与本次种子，自定义数据保留。聚焦证据：修前
`test_custom_title_only_conflict_rolls_back_source_toml_and_seeds` 两参数化用例 `assert 0 == 1`，
修后 `3 passed, 5 deselected in 28.03s`，新增
`test_official_seed_domain_frontier_stage_is_content_validated` 1 passed；frontier E2E 按共享
业务只跑一次策略改为 `qq.official` 单份并 1 passed in 24.14s；当前官方数据全量解析 84 关
通过、正常部署 `returncode 0` 且 `matchers=1 handlers=1`；未跑全量/压测/部署，未验 QQ 真机。

守界线三关可玩序列已在 `develop` 完成（数据提交 `ba89012`）：`domain_frontier.guard.2`
巡守裂隙（`travel_arrival` → `cave.boundary_realm`）、`guard.3` 鏖战边关
（`exploration_battle_victory`，`explore.boundary_rift`/`cave.boundary_realm`）、
`guard.4` 镇纹回响（`exploration_reward` 取 `item.domain_core_fragment` ×1）三关均补齐正文、
目标、行动、首通状态事件、前链（`guard.2→guard.3→guard.4→guard.5`）与失败重试规则，
并列入内容化校验集合。可达性以内容图为准：界隙秘境只有经 `xuantian.war_front` 一条入边，
而魔界战线受每周界战窗口（`weekday_utc=2`，即周三 20:00–23:00 UTC）约束，故三关只在
界战窗口内成行，正文与重试文案如实说明；未新增地点、通路、探索模式、奖池或物品。
聚焦证据：`test_domain_frontier_mainline.py` 1 passed in 24.72s（同一 `qq.official` 共享链
真实结算 18 关，含界隙巡查的战斗胜利与核心碎片掉落，种子按生产随机契约推导而非硬编码），
`test_seed_migration.py` 8 passed in 130.37s（旧官方 blob 升级、重复升级幂等、自定义保留与冲突回退）。
未跑全量/压测/部署，未验 QQ 真机。

领域前线剩余 14 关可玩化已在 `develop` 完成（数据提交 `21a85d1`）：`guard.5` 共铸守门
（`exploration_reward` 取雾隐核心）、`guard.6` 守界封天（经魔界战场与青石镇结算回到领域前线）、
`purify.1–6` 净渊线（云舟渡口抵达、深渊门备材取灵魂晶石与魔核、堕落遗迹取契约线索并击退源头守卫）、
`protect.1–6` 护祖线（祖灵湖取祖灵血并守住祖影、万兽山取兽血与血脉线索、三界贸易口备案），
18 关全部列入内容化校验集合，前链 `guard.5→…→protect.6` 完整、尾关如实留空，每关一条首通状态事件。
可达性按内容区域图核实并据此写正文：领域前线只有青石镇一条入边，界隙秘境只由魔界战场进入，
魔渊集市与堕落遗迹是终端（云舟只在魔渊入口与洞天二层登船），魔界深渊门只能乘云舟抵达，
故 `purify.1` 的目标落在云舟渡口、`purify.4–6` 以堕落遗迹收尾；未新增地点、通路、模式、奖池或物品。
聚焦证据：`test_domain_frontier_mainline.py` 1 passed in 33.10s（同一 `qq.official` 共享链真实结算
18 关，含乘舟、魔界引导、跨日次数与按生产随机契约推导的战斗/掉落）；`test_seed_migration.py` 通过。
未跑全量/压测/部署，未验 QQ 真机。

虚空档案主线 24 关完整可玩化已在 `develop` 完成（数据提交 `fd4842c`）：`recorder.1–8` 记录者线
（抵达第一航道、辨字取残片·甲、守卫战守住灵痕、档案遗迹归位星简、取残片·乙/丙与虚空档案本体、合卷之战）、
`escort.1–8` 护航线（护卷回第一航道、取虚空锚与虚空晶、迎回孤灯、护阵镇潮、借风回舵、共守归途、两跳抵门户）、
`return.1–8` 归乡线（故土回望、拾回旧梦、问归何处、故关再渡、照见来路、归心化桥、万里同门、归乡见天），
24 关全部列入内容化校验集合，前链 `recorder.1→…→return.8` 完整、尾关如实留空，每关一条首通状态事件。
可达性与目标按实际运行时核实：虚空内 `前往` 普通移动可用（写 `travel_sessions`，故 `travel_arrival` 成立），
门户↔第一航道 1800 秒、第一航道↔档案遗迹 2700 秒；档案遗迹无直达门户边，末两关以两跳抵达门户；
`进入虚空航道`/`结算虚空航道` 是另一套锚点航行（写 `void_route_sessions`），本弧不作为目标。
目标只用既有内容：两种探索模式（`explore.void_route` 战斗 45%、`explore.archive_ruins` 战斗 60%，各每日 2 次）
及其奖池物品；未新增地点、通路、模式、奖池或物品。前置 `event.archive_unlock`（周任务解锁，有效期 7 天）、
`event.archive_guard.won` 与 `story.mainline.void_archive.time_fort`（时序堡垒首通）以上下文夹具提供，
真实生产者由既有 `test_void_archive.py`、`test_time_fort_secret_realm.py`、`test_void_ruins_secret_realm.py`
覆盖；目标本身全部真实结算（普通移动、跨日次数、按生产随机契约推导的探索掉落与战斗胜利），未跳过、未放宽阈值。
聚焦证据：`test_void_archive_mainline.py` 1 passed in 71.54s（同一 `qq.official` 共享链真实结算 24 关，
含提前领取被拒、幂等回放、24 条首通事件各 1、三章末关灵石与 codex 奖励）；
`test_mainline_content.py` + `test_mainline_vertical_slice.py` 16 passed；`test_seed_migration.py` 通过；
官方 `剧情/主线.json` 新旧 SHA-256（`a97d5a94…` → `48589e5f…`）与 Git provenance 已登记
`scripts/seed_migrations.json`，迁移测试反向助手只回退本弧 24 关增量。未跑全量/压测/部署，未验 QQ 真机。

道统新章主线 30 关（三线并行）可玩化已在 `develop` 完成（数据提交 `aae19b2`）：`builder.01–10` 建设者线
（旧碑校正、补绘魔界商路与妖界灵脉、三界互市、界隙立标与补缀界壁、汇合三源、立约共修、回望代价、以合道六层抵达道源门）、
`witness.01–10` 见证者线（收录旧誓、听取三界、辨清旧争、见证守卫与互助、核验盟约、保留异议、确认代价、保存全录、把记录交还三界）、
`traveler.01–10` 远行者线（走访玄天、渡过魔土、寻访妖庭、巡查界隙、抵达档案、重返三界、交接道路、携行消息、拒绝捷径、归来开篇）；
30 关全部列入内容化校验集合，三线各自成链、三条线尾关如实留空，每关一条首通状态事件与一个 codex flag。
主线 84 关（玄天 12 + 领域前线 18 + 虚空档案 24 + 道统新章 30）至此全部内容化。
目标只用既有内容：普通移动 16 关、探索取物 10 关、探索战斗胜利 4 关（魔界堕落遗迹/万兽山/祖灵湖/界隙/虚空航道/档案遗迹/深渊门备材），
未新增地点、通路、模式、奖池或物品。可达性按运行时核实：魔渊入口只能乘云舟抵达、界隙秘境入边只有魔界战线与虚空门户、
道源门需合道 L6 + 道果进度 470 + 道果碎片 ×2 且每日 1 次，故 `lane.builder.chapter.10` 的境界由炼虚 L10 对齐为合道 L6
（对齐真实路线门槛，不放宽世界准入）；`dao_echoes.py` 的资格校验随之改为「本关声明资格须不低于故事入口资格」。
校验器新增 lane-aware 尾关规则：带 lane 的故事按本线最大 (chapter, stage) 判定尾关，无 lane 的故事保持原故事级行为。
代码：`dao_echoes_repository.py` 开始路径把本关契约（objectives/retry_message/started_at）冻结进快照，领取路径在目标未完成时
拒绝并抛 `MainlineObjectivesIncompleteError`，`dao_echoes_use_cases.py` 映射为 `MAINLINE_OBJECTIVES_INCOMPLETE`（重复挑战同样重新校验目标）。
修复阻塞本弧的根因：探索境界门槛 `exploration/rules.py` 曾用硬编码 rank 表且止于化神，炼虚及以上一律 rank -1，
使这些修士无法进入任何低于自身境界的探索模式；现改为与主线一致地从 `data/境界/境界.json` 的 `rank` 读取。
聚焦证据：`test_dao_echoes_mainline.py` 1 passed in 17.13s（同一 `qq.official` 共享链真实结算 30 关，含提前领取被拒、
幂等回放、30 条首通事件各 1、30 个 codex flag、三线完成、三界主线资格）；`test_dao_echoes.py` 5 passed（含重复挑战重新校验目标）；
`test_mainline_content.py` + `test_mainline_vertical_slice.py` + `test_mainline.py` + `test_documentation.py` 23 passed；
探索受影响面 `test_exploration*.py` 5 文件 37 passed；官方 `剧情/主线.json` 新旧 SHA-256（`48589e5f…` → `0f7cd87d…`）
与 Git provenance 已登记 `scripts/seed_migrations.json`，迁移测试反向助手只回退本弧 30 关增量（含末关境界还原）。
未跑全量/压测/部署，未验 QQ 真机。

三界塔系统内容化已在 `develop` 完成（数据提交 `0f3b39b`）：新增 `data/特殊/三界塔.json`（kind `three_realms_tower`，
记录 `tower.three_realms`）承载 40 层塔契约——4 段连续层段（1–10/11–20 元婴 L1、21–30/31–40 化神 L1，
每段体力 12、每周 2 次、10/20/30/40 层 boss）、三阵营敌人前缀 `enemy.three_realms_tower`、
首通奖励 `{item.mat.array_sand:2, spirit_stones:60}` 与重复奖励 `{item.mat.array_sand:1}`、
重建声望三键，以及每段的许可旗标（≤20 层 `story.mainline.three_realms`）与重建声望门槛（>20 层 500）。
`three_realms_tower_rules.py` 改为内容驱动并校验（层段连续覆盖 1..40、境界已开放、层数/体力/次数为正、
boss 层落在本段内、奖励引用已开放物品或灵石、factions/重建键与开放集合一致），未知境界或物品引用抛
`ContentError`；新增 `floor_gate()` 让仓库的门槛判断（元婴或三界许可 / 化神或 500 重建声望）由数据给出，
`three_realms_tower_repository.py` 与双人仓库改为传入 `self.content`，`three_realms_tower_duo_rules.py` 继续再导出。
层数、次数、体力、敌人键、奖励数值与声望键全部保持原值（数据化只改变「从哪里读」）。
聚焦证据：`test_three_realms_tower_content.py` 10 passed（合同覆盖 40 层×3 阵营、每个组合的敌人键都能被
战斗层解析、首通/重复奖励与门槛现值一致；并逐项断言校验失败：层段空洞、重叠、未知境界、未知物品、
boss 层越段、factions 不符、max_floor 不符、缺字段）；回归 `test_three_realms_tower.py`、
`test_three_realms_tower_duo.py`、`test_tower.py`、`test_tower_snapshot_integrity.py`、
`test_tower_snapshot_migration.py` 全绿；`data/内容清单.json` 新增该文件并登记种子迁移
（`8121ad7f…`→`e504acb5…`，provenance `eaed711`）。未跑全量/压测/部署，未验 QQ 真机。

虚空塔全 1–90 层内容化目标已完成并合入 `main`：实现提交 `aad6754`、官方种子迁移
`4651b35`，合并提交 `83848c6`。`develop` CI `38857853568` 与 `main` CI `38858424607`
均已通过（Python 3.11/3.12 quality、install-smoke；release job 按条件跳过）：
`data/特殊/虚空塔.json` 现在以 6 个连续段（1–15 风暴、16–30 回响、31–45 碑铭、46–60 见证、
61–75 道源、76–90 登临）承载全部准入境界/名望、体力、UTC 周额度、敌人范围、首领层、首通/首领/练习奖励、
路线图鉴、故事图鉴和展示称号。`void_spire_rules.py` 对 1–90 统一做严格字段、引用、连续覆盖、敌人范围与首领对应、
奖励类型、图鉴和称号校验；`floor_definition`、周额度、奖励、故事/称号与路线图鉴查询均从段内容读取。
仓库入场准入和预览继续保留原 1–30/31–60/61–90 行为，历史 operation、战斗/领奖快照、失败退款和跨适配器
回放不改；路线图鉴使用内容中的稳定键而非运行时拼接。聚焦合同测试 `test_void_spire_content.py` 18 passed，
既有 `test_void_spire.py` 19 passed；迁移/安装回归 `test_seed_migration.py` 8 passed，文档回归 29 passed；
未跑全量/压测/部署，未验 QQ 真机。

专用秘境规则内容化已在 `develop` 完成（提交 `327918c`、`4497735`、`7b4aa3c`）：新增
`data/冒险/秘境专用.json`（kind `secret_realm_instance`，8 条记录）与共享加载器
`adventures/secret_realm_content.py`，7 套专用秘境规则模块（`ancestral_hall`、`ancient_domain`、
`heaven_echo`、`dao_origin`、`demon_abyss`、`boundary_rift`、`legacy_manor`）改为从内容派生全部常量。
记录承载地点、节点（含中文标签与可选节点敌人）、体力、周次/终身次数、过期秒数、准入许可/旗标、
剧情旗标、图鉴条目、首通/重复奖励、组队类型、门票、能量压制、风险 bp、名称别名，以及遗府的境界/线索/作用域。
加载器校验记录须 active、name/desc 非空、地点须已存在（允许刻意锁定地点，如 `cave.ancient_domain`）、
节点非空且 key 唯一、标签非空、体力/次数/过期为正整数、奖励键非空且数量为正、别名非空列表，未知地点抛
`ContentError`。敌人与奖励键按标识符校验：战斗层把内容记录与生成敌人合成解析（三界塔同样只校验敌人前缀），
奖励层含非内容命名空间。节点解析保持稳定 key/中文标签/1 基序号三种写法，遗府保留 `LegacyManorDefinition`
与按实例取用接口，恶魔深渊风险函数仍为代码。审计中发现两处既有悬空引用并如实保留、未新增内容：
`enemy.ancient_domain_lord` 经复核**存在**于战斗层旧 `ENEMIES` 表（`enemy_definition()` 可解析，此前误判源于 grep 输出被 `head` 截断），`item.clue.demon_abyss_echo` 确不在物品内容中，已在后续轮次补齐为同族线索记录。
聚焦证据：新增 `test_secret_realm_instance_content.py` 24 passed（8 条记录合同、7 个模块常量与记录一致、
三种节点别名解析、12 项校验失败用例）；`test_ancient_domain_secret_realm.py`、`test_ancient_domain_open_event.py`、
`test_heaven_echo_secret_realm.py` 10 passed；`test_dao_origin_secret_realm.py`、`test_demon_abyss_secret_realm.py`、
`test_legacy_manor.py` 与其余秘境回归全绿。`test_ancestral_hall_secret_realm.py`（3 项）与
`test_boundary_rift_secret_realm.py`（5 项）的失败经 stash 对照确认为改动前既有失败（战斗/持久化相关），
非本次内容化引入。`data/内容清单.json` 登记新文件并更新种子迁移规则（`e504acb5…`→`15773fe8…`，
provenance `0f3b39ba`）。未跑全量/压测/部署，未验 QQ 真机。

时序堡垒与虚空遗迹两套组队专用秘境内容化已在 `develop` 完成（数据提交 `7a9d47a`、种子迁移 `b04edcb`）：
`data/冒险/秘境专用.json` 扩至 10 条记录，`instance.secret_realm.time_fort`（地点 `void.archive_ruins`、
组队 `secret_realm_time_fort`、境界门 `void_refining` L1、2–5 人、体力 40、周限 1、过期 3600 秒、
许可 `access.void.time_fort`、剧情旗标 `story.mainline.void_archive.time_fort`、首/重奖励阵砂 2/1、
风暴间隔 3 回合伤害 500 bp、守时者敌人、6 节点中文标签）与 `instance.secret_realm.void_ruins`
（体力 50、锚点锁 1、许可与图鉴 `codex.void.route_ruins`、重复奖励虚空晶、10 节点、
裂隙哨卫/档案守卫的稳定与不稳定敌人变体）全部常量改为内容派生，值与原硬编码逐一相同；
`time_fort_rules.py`/`void_ruins_rules.py` 经共享加载器读记录并导出原名称，两个仓库的境界门槛
改用内容境界键（不再内联 `"void_refining", 1`），快照内联 `time_storm` 数值同步改由常量填充；
`combat/party_repository.py`、`secret_realm_use_cases.py` 等消费者不改导入。加载器新增
成员边界（成对声明、min≤max）、境界门（成对声明、开放境界引用）、风暴数值（成对声明）与
节点 `unstable_enemy_key`（须伴随基础敌人、字符串非空、未知节点字段拒绝）校验，均抛 `ContentError`。
官方 `秘境专用.json` 新旧 SHA-256（`7f02246e…`→`5af42df1…`）与 Git provenance 已登记
`scripts/seed_migrations.json`，迁移测试新增反向助手（旧 8 记录 blob 升级、重复升级幂等、
有效自定义变体保留），`test_seed_migration.py` 9 passed。聚焦证据：
`test_secret_realm_instance_content.py` 37 passed（新增两记录合同与 11 项校验失败用例）、
`test_time_fort_secret_realm.py`+`test_void_ruins_secret_realm.py` 8 passed
（混合适配器路线/风暴/重启/奖励与原子准入回归）、`test_secret_realm_intro.py`+
`test_secret_realm_upper.py`+`test_party_combat.py` 10 passed。未跑全量/压测/部署，未验 QQ 真机。

固定跨界贸易内容化已在 `develop` 完成（数据提交 `952314f`、清单种子迁移 `a152cea`）：
新增 `data/经济/跨界贸易.json`（kind `cross_realm_trade`，4 条记录），`economy/cross_realm_trade_rules.py`
的 3 条固定贸易（`trade.xuantian_to_demon` 云铁×10+200 灵石→魔核×1、`trade.xuantian_to_beast`
灵叶×10+200 灵石→妖血×1、`trade.three_realms` 魔核×2+妖血×2→神魂晶×1 双声望 200/周限 3）、
周上限 5、绑定 24 小时、三个贸易地点与全部中文别名改为内容派生，值与原硬编码表逐一相同，
别名映射逐键相等，`resolve_trade`/`trade_definition`/`week_start` 语义不变，未知贸易仍抛 `ValueError`。
新增共享加载器 `economy/cross_realm_trade_content.py`：`trade.defaults` 承载共享周限/绑定/声望默认值，
逐贸易校验 status、name/desc/label 非空、地点存在（允许锁定地点）、物品引用存在、货币成本非负、
物品数量为正、周限/绑定正数、阵营 ∈ {demon,beast,xuantian}、key 唯一、别名非空且无跨贸易冲突，
非法均抛 `ContentError`；刻意锁定的贸易从运行集合排除而非报错。`data/内容清单.json` 登记新文件，
其新旧 SHA-256（`9b0998cf…`→`3c83811…`）与 Git provenance 已登记 `scripts/seed_migrations.json`，
迁移测试新增清单反向助手（旧清单+无贸易文件宿主升级、重复升级幂等），`test_seed_migration.py` 10 passed。
聚焦证据：新增 `test_cross_realm_trade_content.py` 21 passed（默认值/三贸易合同/别名映射逐键相等、
未知贸易 ValueError、18 项校验失败用例、锁定排除）；回归 `test_cross_realm_trade.py` 4 passed、
`test_auction_rules.py`+`test_economy_commission.py` 123 passed。未跑全量/压测/部署，未验 QQ 真机。

洞天设施与终局配方内容化已在 `develop` 完成（数据提交 `ad57c8f`、清单种子迁移 `72bd47f`）：
新增 `data/生产/设施.json`（kind `production_facility`，8 条记录：`facility.defaults` 承载地点
`cave.mist_grotto_2`、维护费 100、工期加成 1000 bp；7 个槽位——灵田 1–4、炼丹房、炼器台、阵基——
含 kind、槽位序号与全部中文别名）与 `data/生产/终局配方.json`（kind `endgame_recipe`，4 条记录：
`endgame.defaults` 承载成功阈值 8000 bp、道果进度上限 1300 与飞升凭证物品键；3 条终局配方——
道果碎片加工、天劫保护阵、飞升凭证——含时长、输入、产出物品/进度、世界功勋、进度/功勋/境界/
终局状态门与地点门）。新增共享加载器 `production/content_rules.py`：逐记录校验 status、name/desc/label
非空、物品/地点/境界引用存在、数值为正、设施 kind ∈ {field,alchemy,artifice,array}、终局状态白名单、
key 唯一、别名无跨记录冲突，非法均抛 `ContentError`。`facility_rules.py` 与 `endgame_rules.py`
改为导入期内容派生并导出原名称，槽位顺序保持既有 field→alchemy→artifice→array 排列，
`resolve_facility`/`facility_for_kind`/`endgame_recipe`/`resolve_endgame_recipe`/`recipe_roll_bp`
语义不变，未知设施仍抛 `ValueError`。`data/内容清单.json` 登记两个新文件，其新旧 SHA-256
（`3c83811…`→`d41820d…`）与 Git provenance 已登记 `scripts/seed_migrations.json`，迁移测试
反向助手同步移除两个新生产文件（旧清单宿主升级、重复升级幂等），`test_seed_migration.py` 10 passed。
聚焦证据：新增 `test_production_content_rules.py` 24 passed（默认值/7 槽位/3 配方合同与别名逐键相等、
未知设施 ValueError、20 项校验失败用例）；回归 `test_production.py`（设施认领/维护/订单槽位生命周期）
8 passed。`test_endgame_producers.py` 1 项失败经 stash 对照确认为改动前既有失败（道源主线目标门
`MAINLINE_OBJECTIVES_INCOMPLETE`，源自 `aae19b2` 目标门先于该测试更新），与本次改动无关。
未跑全量/压测/部署，未验 QQ 真机。

跨界贸易许可内容化已在 `develop` 完成（数据提交 `7b4ae3c`、清单种子迁移 `1c83dbd`）：
新增 `data/经济/贸易许可.json`（kind `trade_permit`，3 条记录：`trade_permit.defaults` 承载
阵营白名单 {demon,beast,xuantian}；`permit.demon_trade`/`permit.beast_trade` 承载标签、阵营、
引路旗标 `quest.demon_intro`/`quest.beast_intro`、声望门槛 80、售价 500 灵石、七日时效与全部
中文别名）。新增共享加载器 `livelihood/trade_permit_content.py`：逐记录校验 status、
name/desc/label 非空、阵营属于白名单、旗标须在 `quest.` 命名空间、经济数值为正、key 唯一、
别名无跨记录冲突，非法均抛 `ContentError`。`livelihood/trade_permit_rules.py` 改为导入期内容
派生并导出原名称（TRADE_PERMITS/ALIASES/resolve_trade_permit 等），全部值与原硬编码表逐一相同，
未知许可仍抛 `ValueError`，签发 operation、快照与幂等回放语义不变。`data/内容清单.json` 登记新
文件，其新旧 SHA-256（`bbeb2104…`→`927b9ef1…`）与 Git provenance 已登记
`scripts/seed_migrations.json`，迁移反向助手同步移除贸易许可文件（旧清单宿主升级、重复升级幂等），
`test_seed_migration.py` 10 passed。聚焦证据：新增 `test_trade_permit_content.py` 18 passed
（合同与常量一致、别名逐键相等、未知许可 ValueError、14 项校验失败用例与加载期重复键拒绝）；
回归 `test_trade_permit_dispatch.py` 3 passed。未跑全量/压测/部署，未验 QQ 真机。

灵兽蜕变内容扩展（Goal D）已在 `develop` 完成：`data/灵兽/灵兽.json` 5 → 7 条记录、
`data/灵兽/蜕变.json` 1 → 3 条蜕变边。新增两条蜕变边 `beast.evolution.iron_rat_2`
（`beast.iron_rat`→`beast.jade_rat`，兽类，18 级/60 好感/技能位 2，成本 `item.ancestral_blood`×2 +
600 灵石）与 `mount.evolution.bamboo_deer_1`（`mount.bamboo_deer`→`mount.cloud_elk`，骑乘，
12 级/50 好感/技能位 1，成本 `item.beast_blood`×2 + 500 灵石），各源只保留一条出边以免
`source_key` 解析歧义；新增两个蜕变形态 `beast.jade_rat`（玉背鼠，1–30 级，
`exploration_discovery_bp` 500）与 `mount.cloud_elk`（云角鹿，1–25 级，500），沿用既有
`companion.evolution` 来源、`item.food.coarse_spirit_rice` 喂养与
`exploration_discovery_bp` 效果白名单，容量 3/2 与既有同 kind 记录一致；成本只引用既有闭合材料
（`item.ancestral_blood`/`item.beast_blood`）与灵石。运行时未改：`companion_evolution_definitions`
内容派生照常解析，`蜕变灵兽 <实例>` 对兽类与骑乘两条边均按快照结算（实例变为对应形态、
`evolution_stage=evolved`、技能位按边生效），已蜕变实例再蜕变被拒且不扣材料，冻结回执/幂等回放
语义不变。官方 `灵兽/灵兽.json`（`1702a0ef…`→`59106625…`）与 `灵兽/蜕变.json`
（`3b321f3f…`→`f354db00…`）已登记 `scripts/seed_migrations.json`。
聚焦证据：新增 `test_companion_evolution_content.py` 2 passed（三边合同与单出边、形态等级/效果/
容量、成本闭合、真实运行时兽类与骑乘两条边结算且重复蜕变被拒）；回归
`test_companions.py` 等 35 passed。未跑全量/压测/部署，未验 QQ 真机。

日常修行变体（Goal E）已在 `develop` 完成：`data/任务/任务.json` 日常任务 11 → 17 条
（`cultivation_exploration` 2→4、`daily_life` 4→6、`other` 5→7，`claim_group=daily` 全部 active），
新增 6 条任务全部只引用真实 `operations` 账本条目与既有开放内容，未新增物品/地点/命令、未改选择逻辑：
高阶探索（`explore.void_route`）与元婴探索（`explore.demon_abyss`）各补一条深层探索变体；
宗门兑换（`social.sect_exchange`，四个既有宗门兑换项）补 `daily_life`；灵树浇水
（`routine.spirit_tree.water`）补 `daily_life`；完成派遣（`specials.settle_dispatch`，outcome
success/partial/delayed）与领取挂机（`specials.claim_idle`，status claimed）补 `other`。
规则层把「同一 operation 只能归属一条任务」收紧为「同一 operation 的多条任务判定条件不得重叠」：
`daily_quest_rules.daily_task_definitions` 新增 `_conditions_overlap`（任一共享字段取值集合不相交即视为
不重叠，无共享字段则保守判为重叠并拒绝），使 `exploration.settle`/`exploration.settle_combat` 可同时
服务近郊采集与两条高阶变体；`daily_quest_repository._project_daily_task_sources` 相应移除
`sources overlap` 硬拒绝，改由既有 `daily_task_events` 逐 (task, operation) 幂等投影，一条结算可
分别记入多条任务且重复请求不重复计数，快照/幂等/回放语义不变。同时把既有 `task.daily.cultivation` 的来源判定恢复为 `result: {}`（任何结算修炼都计入），修正前序改动误将默认调息修炼排除、导致该任务无法完成的语义回退。官方 `任务/任务.json` 新旧
SHA-256（`be7a4098…`→`c219c608…`，旧值 provenance 修正为完整 40 位
`cf72c83cb1427a24d80e57e03fb9202effbc0959`）已登记 `scripts/seed_migrations.json`。
聚焦证据：`test_daily_variants_content.py` 7 passed（三组池形状 4/6/7=17、每条来源 operation 均为
包内真实结算、探索 mode 为开放模式且境界高于新手档、新变体目标地点开放、同 operation 无重叠谓词）；
回归 `test_daily_tasks.py` 等见下。未跑全量/压测/部署，未验 QQ 真机。

跨界贸易渠道扩展（Goal F）已在 `develop` 完成（数据提交 `40df9d1`、清单种子迁移与内容测试
`425bb15`）：`data/经济/跨界贸易.json` 贸易记录 3 → 5 条（`trade.defaults` 不计入），
新增 `trade.xuantian_to_demon.array_sand`（阵砂×10 + 200 灵石 → 魔核×1 @ `demon.abyss_market`，
demon 200 门、复用默认周限 5/绑定 86400）与 `trade.three_realms.soul_crystal`（神魂晶×1 →
云铁×10 @ `beast.three_realms_trade_port`，beast 200 单门 + demon/beast 200 双门、周限 3），
全部输入/输出物品、地点、阵营、声望键、周限与绑定时长取自既有内容，未新增物品/地点/许可/命令、
未改 DB 与快照语义；两条贸易的中文别名并入既有别名表且无跨贸易冲突。官方 `跨界贸易.json`
新旧 SHA-256（`1f87578a…`→`7f95291a…`）与 Git provenance 已登记 `scripts/seed_migrations.json`，
迁移测试新增反向助手（旧 4 记录 blob 升级、重复升级幂等、有效自定义变体保留）。修复 CI 中该
切片的 2 项失败：两个种子迁移用例原用 `deploy(host, data_only=True)`，data-only 不安装源码却仍
执行 `--validate`，宿主预置的占位 `__init__.py` 不注册 matcher，必然报“插件已加载但没有注册
matcher”（旧宿主则报“宿主插件入口不存在”），且备份目录断言误指 `data/.xiuxian3`；现改用与其他
种子迁移用例一致的完整 `deploy(host)` 并断言 `matchers=1 handlers=1`，备份目录改为
`<host>/.xiuxian3/backups`（`425bb15` 的 CI 在 3.11/3.12 均复现同一 2 项失败，本地同序复现一致）。
聚焦证据：
`test_cross_realm_trade_content.py` 27 passed（5 条贸易合同逐字段、别名逐键相等、
22 项校验失败用例、新贸易只引用闭合物品与开放地点、声望不足拒绝且零写）；
回归 `test_cross_realm_trade.py`+`test_cross_realm_events.py`+
`test_cross_realm_void_frontier_content.py`+`test_documentation.py` 55 passed。
未跑全量/压测/部署，未验 QQ 真机。

引导内容第三阶段（Goal H）已在 `develop` 完成：`data/引导/引导.json` 引导记录 3 → 6 条，
按记录补齐 `label`/`command`/`aliases` 并新增三条修行者（cultivator）引导 `guide.mine_entry`
（矿区准入指路，命令 `矿区`）、`guide.dispatch_entry`（派遣指路，命令 `派遣`）与
`guide.secret_realm_entry`（秘境指路，命令 `秘境`），三者 `requirements` 均为
`[{type: stage, stage: cultivator}]`、无消耗、`repeatable`、`output` 为 `intro_flag`，只引用既有
生产与探索入口，未新增物品/地点/命令。规则层 `player/intro_rules.py` 改为内容派生
（`guide_definitions`/`guide_labels`/`guide_commands`/`guide_alias_map`/`guides_for_stage`/
`mortal_guides`），并保留 `GUIDE_READ_WORLD`/`GUIDE_GATHER_BLOOD_GRASS`/`GUIDE_CHOOSE_SERVICE`/
`INTRO_GUIDES` 全部既有公开名字；`intro_complete()` 只统计 `stage == mortal` 的记录，扩表不影响
「毕业」语义。阶段门与效果派发解耦：`player/repository.py::_complete_intro_once` 不再硬编码每条
引导的分支，改由记录自身的 `requirements`（阶段/地点）判定准入（不在当前阶段可用的引导仍抛
`PLAYER_STAGE_CONFLICT`）、由 `cost`/`quantity_range`/`output_type` 派发消耗与奖励，`stage_advanced`
仍要求玩家处于 `mortal` 且凡人三引导齐备；`player/intro_use_cases.py` 的进度与提示按阶段过滤
（凡人见 `n/3`，修行者只计其自身层），消息按记录 `label`/`desc` 渲染并为新引导走通用分支。
官方 `引导/引导.json` 新旧 SHA-256（`ee7e3980…`→`26be7bd8…`）已登记 `scripts/seed_migrations.json`，
反向助手同时保留更早的 `5a63404e…` 来源以便旧宿主升级。聚焦证据：新增 `test_guide_stage2_content.py`
8 passed（两层合同与闭合引用、别名逐键相等、凡人毕业只认凡人三引导、按阶段过滤分母、修行者三引导
真实结算且回放不重复扣费/发奖、毕业前拒绝并不写入、凡人全流程毕业仍为 `seeker`）、
`test_onboarding.py` 4 passed；`test_seed_migration.py` 新增两条引导迁移用例（旧 blob 升级 + 重复
幂等、自定义变体保留），CI 同序复现 `test_seed_migration.py`+`test_installation_docs.py` 43 passed。
另修一处本片回归：内容化的选择项若只列三条生产，`服务教学` 提示会少一项，与 `service.cook_meal`
的 `teaching.service = cooking` 前置不符，故记录 `options` 补齐为 alchemy/artifice/formation/cooking，
`test_player_interaction.py` 恢复通过；全量 2686 passed / 39 failed，逐一与 HEAD 工作树比对后
39 项全部为未改动 HEAD 上同样失败的既有失败（`test_adapter_simulation.py`、`test_data_completion.py`、
`test_boundary_rift_secret_realm.py` 等），本片未新增失败。未跑压测/部署，未验 QQ 真机。

时序行卷（Goal I）已在 `develop` 完成：`data/道历/行卷.json` 行卷 1 → 2 卷，新增第二卷
`pass.timetrace`（21 日、24 级、每级 60 点、日上限 120、周上限 500），只投影采集
（`exploration.settle` 20）、灵田收获（`livelihood.harvest` 25）、生产完成
（`production.complete` 25）、派遣结算（`specials.settle_dispatch` 30）与时序堡垒结算
（`time_fort.settle` 40）五种已结算来源；免费线发时痕草与既有材料/名望（`local.dao_service`，
上限 1000），付费线需当前有效月道契并发时痕草、阵砂、配方线索与灵木水分券。
规则层按卷校验来源集合与付费物品白名单（问道卷八源/两物品不变），快照身份按数据库行的卷键校验、
恢复快照不读现行内容；仓储以角色最近一期行卷结算，同一角色同时仅一卷在途，
`开始行卷 [卷名]` / `问道行卷 [卷名]` 用既有命令的可选参数选卷（`时序`/`时序行卷`/`timetrace`/
`pass.timetrace`），未新增命令或数据库表；`pass.wayfaring.start`/`claim` 与既有 request_hash
不变，换卷后旧卷仍可查询，领取仍按原 operation 回放。种子迁移登记
`58ab35ef…`→`69c890f3…`，provenance `36c9db9`。聚焦证据：新增
`test_scroll_volume2_content.py` 14 passed（卷合同、来源集合隔离与坏来源拒绝、奖励来源闭合
含时痕草产出池、日/周点数上限与触顶 0 点、free/paid 实发与回放幂等、换卷后重启持久化与旧卷查询、
未知卷名拒绝）；行卷既有回归 `test_wayfaring*.py` 120 passed；`test_seed_migration.py`
新增迁移/自定义保留用例（`-k wayfaring` 3 passed）；`test_documentation.py` 2 passed；
`compileall` 与 `git diff --check` 通过。未跑全量/压测/部署，未验 QQ 真机。

跨域内容一致性收口（Goal J）已在 `develop` 完成：`data/内容清单.json` 登记 62 份与磁盘
63 份数据 JSON 双向一致（唯一差集为清单自身，清单不登记自己）；Goals A–I 改动的 11 个
官方种子全部具备迁移规则，其中 Goal A 的 `图鉴/条目.json` 原缺规则，现登记旧 blob
`d51b99c1…`（provenance `44be5213…`）与现行 blob `bb71dd2f…`（发货提交 `2ea7007`）；
`scripts/seed_migrations.json` 17 条规则的 `new_sha256` 全部与现行文件一致。
`test_seed_migration.py` 新增 A–I 覆盖钉值（改动种子缺规则即失败）、清单覆盖用例、
6 个反向助手（`图鉴/条目`、`灵兽/蜕变`、`生产/配方` 由现行种子重建；`任务/任务`、
`道具/丹药`、`灵兽/灵兽` 因切片整file重排改为 `test/fixtures/official_seeds/` 归档旧 blob
并按指纹校验）与 `图鉴/条目` 部署用例：旧宿主同时迁移图鉴与地点两枚种子（避免 17 条
codex 悬空）、备份、重复部署幂等、自定义种子保留。计数复核
`test_material_content.py`+`test_combat_content.py` 29 passed（材料矩阵与战斗内容钉值
未因 A–I 漂移）。未重做 A–I 内容，未跑全量/压测/部署，未验 QQ 真机。

功业录内容化（v0.8）已在 `develop` 完成（数据与加载器 `7f3e085`、清单迁移 `3eab8e1`、
内容基线 `6dcd8f3`）：功业定义从 `routine/rules.py` 的 Python 元组迁到
`data/功业/功业.json`（kind `achievement`，6 条），新增 `routine/achievement_content.py`
校验字段集合、`achievement.` 键前缀、奖励白名单（地方名望/服务信誉/道号）、道号存在且未关闭、
地方名望键与上限可解析、`status` 取值与空内容整域拒绝；`rules.ACHIEVEMENTS` 改由内容派生并
保留同名导出，`achievement()` 支持按传入内容解析，`routine/use_cases.py`、`routine/repository.py`
与其他 `ACHIEVEMENTS` 导入方的展示/序号解析/领取路径不变。既有五条（首次问安/首次生产/
首次派遣/五条图鉴/试炼塔十层）语义与数值不变，新增 `achievement.three_day_checkin`
（三日不辍，第三条问安，名望 5，复用既有 `routine.checkin.daily:3` 投影，未新增事件类型）。
关闭语义落地：`closed` 条目保留序号占位，未领取显示“内容未开放”、领取返回 `CONTENT_CLOSED`，
已领取记录与原始奖励不回退；`locked`/`planned` 只登记不入表，未知状态整域拒绝。
`data/内容清单.json` 登记新文件并更新清单指纹（`927b9ef1…`→`dd4e5e6d…`），迁移规则
`new_commit` 指向实际发货提交。聚焦证据：`test_achievement_content.py` 19 passed（内容合同、
12 项坏记录拒绝、空内容拒绝、关闭与锁定语义、第三条问安真实领取、回放与重复领取）；
`test_routine.py` + `test_documentation.py` 17 passed；`test_seed_migration.py -k manifest`
3 passed（旧宿主升级、幂等、自定义种子保留）。develop CI（Quality and Release `40680500166`，
head `6dcd8f3`）成功。未跑全量/压测/部署，未验 QQ 真机。

道号与道契内容化（v0.9）已在 `develop` 完成（数据与加载器 `24ecef2`、清单迁移 `cbcaa9c`、
内容基线 `66d34f6`）：`HONOR_TITLES`（17 条）与 `DAO_CONTRACTS`（3 条）从 `routine/rules.py`
的 Python 元组迁到 `data/道历/道号.json`（kind `honor_title`）与 `data/道历/道契.json`
（kind `dao_contract`），由新增 `routine/routine_content.py` 统一校验字段、键前缀、奖励数值与
`status`；`rules` 保留同名导出与顺序，`功业录`/`佩戴称号`/`我的道契`/`激活道契`/`领取道契`
路径不变。道号 `source_event` 允许为空（5 条行卷道号由行卷奖励直接写入），其余沿用既有来源
投影；道契时长/价格/每日与激活奖励/名望周期与旧表逐字段一致。`功业录` 对未获得的道号显示
获取提示（`hint`），已获得/已佩戴行不变，`data.titles` 增加 `hint` 字段。关闭语义沿用 v0.8：
`closed` 道号保留序号占位、不再自动授予、已获得仍可佩戴；`closed` 道契不可新激活并返回
`CONTENT_CLOSED`（凭证不消耗），已激活权益的领取不受影响；`locked`/`planned` 只登记不入表，
未知状态与空表整域拒绝。`data/内容清单.json` 登记两份新文件并更新清单指纹
（`dd4e5e6d…`→`12ed228d…`），迁移规则 `new_commit` 指向实际发货提交。聚焦证据：
`test_routine_content.py` 24 passed（逐字段一致、18 项坏记录拒绝、空表拒绝、关闭/锁定语义、
功业录提示、关闭道契拒绝激活且凭证未消耗）；`test_routine.py` + `test_documentation.py`
17 passed；`test_void_spire.py` 19 passed（道号键消费方）；`test_seed_migration.py -k manifest`
3 passed（旧宿主升级、幂等、自定义种子保留）。develop CI（Quality and Release `40708847422`，
head `66d34f6`）成功。未跑全量/压测/部署，未验 QQ 真机。

远古洞天与魔渊深层探索开放（v0.7 探索基线）已在 `develop` 完成（数据与测试 `c35c1b7`、
种子迁移 `942d547`、内容基线 `39e5ce7`）：`cave.ancient_domain` 与 `demon.abyss_depths`
由 `locked` 改为 `open`（准入与区域入边不变），补上两处地点原本悬空的动作——
`explore.ancient_domain`（1200 秒/18 体力/2 精力/每日 2 次/战斗 60%）与
`explore.abyss_depths`（1500 秒/22 体力/3 精力/每日 2 次/战斗 75%），各带真实奖池与
遭遇池；新增四名地点绑定敌人（洞天守禁灵卫/洞天残影、深渊潜行者/魔气怨影，化神 L1，
复用既有敌人技能与掉落池族）与两个遭遇池，不新增物品、技能或掉落池类型。
远古洞天开放后，此前因地点不可进入而实际不可达的 v0.4 三人秘境
`instance.secret_realm.ancient_domain` 亦随之可达。五份改动种子（地点/模式/敌人/遭遇池/奖励）
均登记旧/新 SHA-256 与 provenance，`地图/地点.json` 反向助手同时回退状态翻转与 codex 属性。
聚焦证据：`test_exploration_depths_content.py` 8 passed（引用闭合、6 项坏记录拒绝、
魔渊深层真实开始→过期→结算→回放）；`test_combat_content.py`+`test_material_content.py`+
`test_exploration_integrity.py`+`test_documentation.py` 43 passed（战斗钉值 61/39/17/33/15/14）；
`test_seed_migration.py -k "location or manifest"` 4 passed（旧 locked 宿主升级、自定义保留）。
develop CI（Quality and Release `40733834366`，head `39e5ce7`）成功。未跑全量/压测/部署，
未验 QQ 真机。

竞技场家族内容化已在 `develop` 完成（数据提交 `dbb563f`、清单种子迁移 `0a6e71d`）：
新增 `data/特殊/竞技场.json`（kind `arena_rule`，4 条记录：`arena.defaults` 承载段位带
500/1000/1500 与阵营清单 {xuantian,demon,beast}；`arena.spar` 承载个人竞技快照 7 天/30 分钟、
每日挑战 5、周段位 20、每日练习 3、计费对手 2、15 回合、积分 25/-10/5；`arena.team` 承载组队
2–3 人、快照 7 天/30 分钟、每日 3、积分 20/-8；`arena.three_realms` 承载元婴 L1 准入、许可
标识符与三阵营）。新增共享加载器 `specials/arena_content.py`：逐记录校验 status、name/desc、
正数数值、积分增量为整数、段位带严格递增、队伍规模 min≤max、境界引用开放、阵营白名单与
mode key 唯一，非法均抛 `ContentError`。`arena_rules.py`/`team_arena_rules.py`/
`three_realms_arena_rules.py` 改为导入期内容派生并导出原名称，`rating_band` 改走内容段位带，
许可键按标识符校验（运行时不作物品解析）。全部值与原硬编码表逐一相同，段位判定、积分语义、
模式次数上限、组队模拟与回放行为不变。`data/内容清单.json` 登记新文件，其新旧 SHA-256
（`5a8eba45…`→`bbeb2104…`）与 Git provenance 已登记 `scripts/seed_migrations.json`，迁移反向
助手同步移除竞技场文件（旧清单宿主升级、重复升级幂等），`test_seed_migration.py` 10 passed。
聚焦证据：新增 `test_arena_content.py` 27 passed（三记录合同与常量一致、段位边界、积分语义、
模式上限、20 项校验失败用例）；回归 `test_arena.py`+`test_team_arena.py`+
`test_three_realms_arena.py` 9 passed、`test_arena_migration.py`+`test_arena_projection.py`+
`test_arena_recovery.py`+`test_arena_stats.py` 12 passed。未跑全量/压测/部署，未验 QQ 真机。

时序福地探索闭环已在 `develop` 完成（功能提交 `d059905`、材料种子迁移记账随收口提交）：
`cave.time_garden`（时序福地）此前为开放可达地点但 actions 许诺的 `explore.time_garden`
不存在；本切片补齐全链路——探索模式（炼虚 L1、900 秒、体力 25 + 精力 3、每日 2 次、
遭遇概率 5000bp）、地点绑定敌人 `enemy.time_garden_echo`（时园时光残影）与
`enemy.time_garden_keeper`（时园守园人，炼虚层属性，掉落走 `reward_pool.enemy.void`）、
遭遇池 `encounter.void.time_garden`（60/40）、加权奖励池
`reward_pool.exploration.time_garden`（时痕草+灵石，稀有虚空晶）、新材料
`item.herb.time_trace`（时痕草，含 `gathering_sources` 边）、生产消费者
`recipe.void.time_refine`（时露调和：时痕草×2+虚空晶×1→虚空能量晶×1，失败退 1+1）、
`source.item.void_materials` 登记 asset_keys 与 exploration.settle 通道完成来源闭合。
材料矩阵由 12 材料/17 来源/9 模式/29 消费者增至 13/18/10/30，`validate_material_content`
通过。战斗层敌人须与探索地点绑定（`enemy.void_route_echo` 等绑定他处不可复用），
故新增两条地点绑定敌人而非复用。聚焦证据：新增 `test_time_garden_content.py`
8 passed（模式/物品/奖励池/遭遇池合同、来源闭合、地点 actions 无悬空引用、坏变体拒绝）、
`test_time_garden_gameplay.py` 2 passed（真实命令链：战斗胜利结算、和平结算、
幂等回放、每日上限、境界门与地点门拒绝）、`test_combat_content.py` 计数钉值更新
（敌人 55→57、profiles 33→35、遭遇池 14→15、候选 27→29、消费遭遇 12→13）、
`test_material_content.py` 矩阵钉值更新、`test_documentation.py` 2 passed；
受影响回归 `test_exploration.py` 1 项失败经 stash 对照确认为改动前既有失败。
`道具/材料.json` 新旧 SHA-256（`677d37e3…`→`a4afe7f5…`）与 Git provenance 已登记
`scripts/seed_migrations.json`，迁移反向助手移除 time_trace 记录（旧宿主升级、
重复升级幂等、自定义保留）。其余 6 个变更数据文件（遭遇池/敌人/奖励/模式/来源/配方）
均为种子迁移体系建立后新增的官方文件，按既有先例不设迁移规则。未跑全量/压测/部署，
未验 QQ 真机。

时序主题消耗品与炼丹/阵法配方已在 `develop` 完成（2026-10-22 Goal 6，实现
`1d643e6`、迁移记账 `cfe7d58`）：时痕草此前只有 `recipe.void.time_refine` 一个
通用消费者，三大辅修均无时序主题配方；本切片补齐——`item.pill.time_ward`
（时序护心丹，rare，恢复体力 30、5 分钟同物品冷却，沿用 `restore_choice`
效果白名单，绑定角色）、`recipe.pill.time_ward`（炼丹：时痕草×1+灵叶×2→
时序护心丹×1，炼丹房设施，成功 4500bp/高品 8000bp，失败按 1+1 退款，
感气期 L1 入门，与同境界丹药配方对齐）、`recipe.array.time_anchor`
（时序锚定阵：时痕草×2+阵砂×1→既有基础聚灵阵 `item.array.gathering_basic`，
布阵辅修+阵法设施，成功/高品阈值与基础聚灵阵一致）；生产/物品/阵法记录均通过
加载器校验，`validate_material_content` 消费者 30→32。聚焦证据：
`test_time_craft_content.py` 4 passed（配方合同、可用效果白名单断言、
体力恢复+冷却、炼丹门通过、缺料原子零写拒绝）；生产/物品/材料/M9 内容完整性/
文档组 62 passed（含 M9 钉值同步 recipes 35、modes 20、enemies 57，均为
时园切片后未同步的过时值）；`道具/丹药.json` 与 `生产/配方.json` 新旧 SHA-256
与 d059905 来源已登记 `scripts/seed_migrations.json`。未跑全量/压测/部署，未验 QQ 真机。

中高阶派遣内容化已在 `develop` 完成（数据提交随收口推送）：`data/生活/生活.json`
派遣由 6 条增至 16 条，为 foundation/golden_core/nascent_soul/soul_transformation/
void_refining 各补 2 条——雾隐洞天巡护（阵砂×1–2+灵石 60+镇声望）、云城商队护送
（灵叶×2–3+灵石 70+云城声望）、云铁矿区勘测（云铁×1–2+灵石 90+云城声望）、
丹材押运（灵魂晶×1–2+灵石 100）、堕落遗迹哨探（魔核×1–2+灵石 130+集市声望）、
万兽山兽群清点（兽血×1–2+灵石 140+贸易口声望）、领域前线文书接力（阵砂×2–3+
灵石 180+前线声望）、魔渊集市货单核对（魔核×2–3+灵石 200+集市声望）、
时序福地花畦打理（时痕草×1–2+灵石 240）、虚空航道信使（灵魂晶×2–3+灵石 260+
贸易口声望）。每条含 duration（1200–3600 秒）、daily_limit 2–3、体力/精力成本
（4→9 随境界递增）、realm+min_layer 门槛、risk weights（总和恒 10000，高阶加险）、
success/partial 奖励与 failure_refunds ⊆ cost。全部奖励物品均为来源闭合材料
（gathering_sources 或 source.item.void_materials 登记），local.* 声望键均可被
`local_reputation_maximum` 解析。加载器校验全通过；未知派遣与别名冲突 ValueError
语义保留。聚焦证据：新增 `test_dispatch_rules_content.py` 5 passed（十记录加载、
每境界 ×2 覆盖、奖励来源闭合、合同现值钉住、6 项拒绝用例）；`test_dispatch.py`
闭合表钉值扩展 6→16、`test_dispatch_reserved_inventory.py`+`test_trade_permit_dispatch.py`
+`test_idle.py`+`test_dispatch_content.py` 全绿。`生活/生活.json` 无既有迁移规则，
按先例不新增。未跑全量/压测/部署，未验 QQ 真机。

魔界主线任务内容化已在 `develop` 完成（数据提交 `30a756f`、清单种子迁移 `bd2305e`）：
新增 `data/任务/跨界任务.json`（kind `cross_realm_quest`，2 条记录：`cross_realm_quest.defaults`
承载阵营白名单 {demon,beast,xuantian}；`quest.demon_main_1` 承载标签「魔界主线」、证据模式
`explore.demon_abyss` 目标 2、魔界声望 200、元婴 L1 门槛、授予旗标 `access.demon.fallen_ruins`
与中文别名）。新增共享加载器 `quests/cross_realm_quest_content.py`：逐记录校验 status、
name/desc/label 非空、探索模式引用须为开放模式（锁定模式与未知模式分别报错）、境界引用须开放、
阵营属于白名单、数值为正、key 唯一、`access.` 命名空间、别名无跨记录冲突，非法均抛 `ContentError`。
`quests/cross_realm_rules.py` 改为导入期内容派生并导出原名称；`demon_mainline_realm_ready` 不再读
止于渡劫的硬编码境界阶表，改取 `data/境界/境界.json` 的 `rank`（表外境界不再误判 -1，未知境界 -
1 拒绝）；领取仓库把内容束传入境界门，快照内联的 `required_realm`/`required_layer` 同步改由
常量填充。全部值与原硬编码逐一相同，导出名、领取 operation、快照与幂等回放语义不变。
`data/内容清单.json` 登记新文件，其新旧 SHA-256（`d41820dc…`→`5a8eba45…`）与 Git provenance 已登记
`scripts/seed_migrations.json`，迁移反向助手同步移除跨界任务文件（旧清单宿主升级、重复升级幂等），
`test_seed_migration.py` 10 passed。聚焦证据：新增 `test_cross_realm_quest_content.py` 20 passed
（合同与常量一致、境界门行为、16 项校验失败用例、未知任务拒绝）；回归 `test_demon_mainline.py`+
`test_repository_boundaries.py` 5 passed。`test_high_realm_quests.py` 3 项失败经 stash 对照确认为
改动前既有失败，与本次改动无关。未跑全量/压测/部署，未验 QQ 真机。

社交规则内容化与悬空引用修复已在 `develop` 完成（提交 `8646f8b`、`b01bd27`、`45800b1`、`83416d4`）：
补齐缺失的 `item.clue.demon_abyss_echo` 物品记录（同族线索形状，名称沿用既有标签表「深渊残响线索」，
筑基 L1 与深渊入口一致），使恶魔深渊首通奖励与深渊残响遗府的线索引用可解析；同时更正上一轮关于
`enemy.ancient_domain_lord` 的误判——该敌人存在于战斗层旧 `ENEMIES` 表且 `enemy_definition()` 可解析，
此前结论源于 grep 输出被 `head` 截断。
新增 `data/社交/玩家互动.json` 的 `social.mentor` 与 `social.party` 记录及共享加载器 `social/social_content.py`
（校验 active、name/desc、正数、境界/地点引用、`party_type` 唯一、min≤max、别名非空）。
`mentor_rules.py` 的 `MENTOR_*` 常量与 `party_rules.py` 的 11 个队伍定义、人数/时限常量、
`party_definition_for()` 改为内容派生，值与现值逐一相同，`party_boundary` 别名与未知类型 `ValueError` 语义保留；
`is_master_eligible()` 不再读止于渡劫的硬编码境界阶表，改取 `data/境界/境界.json` 的 `rank`，既有境界行为不变，
超出旧表的境界不再被误判为 -1。`partner_rules.py` 经核对已是内容驱动，本轮未改动。
聚焦证据：新增 `test_social_rules_content.py` 19 passed（师徒/队伍合同与模块常量一致、11 个定义逐字段一致、
别名与未知类型语义、旧表外境界判定、13 项校验失败用例）；`test_mentor*.py` 5 文件 167 passed、
`test_party*.py`/`test_cross_realm_party.py`/`test_partner*.py` 4+106+15 passed、
`test_demon_abyss_echo_legacy.py`/`test_content.py` 39 passed、`test_seed_migration.py` 8 passed
（`道具/材料.json` 种子规则更新为 `677d37e3…`，provenance `8646f8b`）。未跑全量/压测/部署，未验 QQ 真机。

事件/赛季与宗门规则内容化已在 `develop` 完成（提交 `c8bcbae`、`c32948a`、`9294d18`）：
`data/事件/赛季.json` 新增 `season.three_realms`（28 天/领取 7 天/名额 100/三榜单标签）与 `season.final_heaven`
（35 天/领取 7 天/名额 10/三榜单含标题键与分数/章节权益 `chapter.final_heaven`），新增 `events/season_content.py`
校验状态、名称/描述、正数天数与名额、带时区锚点、非空且唯一且带标签的榜单；`three_realms_rules.py`、`rules.py`、
`season_rules.py` 的天数/领取/名额/锚点/榜单/章节权益改为内容派生，值与现值逐一相同，赛季窗口 id 与边界不变。
`event.demon_invasion` 新增 `action_aliases`，`demon_rules.py` 的 `DEMON_ACTION_VALUES` 改为内容派生并校验
动作键属于该事件自身的 `public_event.contributions`（不再另设硬编码动作集合），映射与公共事件配置哈希不变。
`data/社交/玩家互动.json` 新增 `social.sect`，`social_content.py` 增加 `sect_rules_record()`，`sect_rules.py` 的
创建成本/成员上限/仓库容量/申请与加入时限改为内容派生（角色、名称正则与校验保持代码）。
聚焦证据：新增 `test_event_sect_content.py` 19 passed（两条赛季合同与模块常量一致、榜单逐字段一致、窗口 id 与
天数一致、动作映射一致且属于该事件贡献键、宗门数值与 `SECT_*` 一致、13 项校验失败用例）；回归
`test_final_heaven_season.py`/`test_three_realms_arena.py` 21 passed、`test_demon_event.py`/`test_events.py`
8 passed、`test_sect_exchange.py`/`test_sect_alliance_beacon.py`/`test_social.py` 16 passed。
未跑全量/压测/部署，未验 QQ 真机。

宗门子系统规则内容化已在 `develop` 完成（提交 `0ab6cb3`、`ccdc80b`、`2538646`）：`data/社交/玩家互动.json` 新增
`social.sect_alliance`（等级门槛 5/确认 24h/持续 7 天/研究周上限 3/违约费 10000/冷却 24h）、`social.sect_beacon`
（锚成本 10/阵砂 30/建造 24h/维护 2/航线折扣 1）、`social.sect_exchange`（日上限 5/4 项捐献物品与中文别名/2 条供给配方
含材料与贡献 100/200/4 个兑换项含标签成本物品数量/10 条输入别名）与 `social.sect_war`（war_key、锚点 2025-01-06Z、
每周 2 轮、30 分钟、报名费 2000、参战 10 人、等级 4、成员门槛 20、宗门奖励 100、成员奖励 30、领取 24h、动作分值表）。
`social_content.py` 新增 `sect_alliance_record()`/`sect_beacon_record()`/`sect_exchange_record()`/`sect_war_record()`
与 `_positive_fields()`/`_item_key()`/`_anchor_datetime()` 助手，校验物品引用存在、offer key 唯一、别名指向有效目标、
材料数量为正、锚点带时区、动作分值为正。四个规则模块的常量与表（含 `SECT_EXCHANGE_OFFERS`/`SECT_SUPPLY_RECIPES`/
`SECT_DONATION_*`/`SECT_EXCHANGE_ALIASES`/`SECT_WAR_ACTION_VALUES`）改为内容派生，`contribution_value()` 不再内联硬编码分值表，
`resolve_sect_exchange_offer()`、`alliance_week_id()`、轮次窗口与 `SectExchangeOffer` 保持不变。
聚焦证据：新增 `test_sect_subsystems_content.py` 28 passed（四子系统记录与模块常量/表逐字段一致、兑换解析与动作分值行为不变、
轮次窗口 id 与边界不变、21 项校验失败用例与缺记录用例）；回归 `test_sect_alliance_beacon.py` 2 passed、
`test_sect_exchange.py` 7 passed、`test_sect_war.py`/`test_sect_war_federation.py` 3 passed。
未跑全量/压测/部署，未验 QQ 真机。

跨界事件指令与虚空前线赛季内容化已在 `develop` 完成（提交 `0de04d3`、`9033570`）：`data/事件/事件.json` 为
`event.beast_trade`/`event.boundary_rift`/`event.ancient_domain_open` 追加 `action_aliases`，`cross_realm_rules.py`
新增 `cross_realm_action_values()` 并校验动作值属于该事件自身的 `public_event.contributions`；`data/事件/赛季.json`
新增 `season.void_frontier`（28 天/领取 7 天/周上限 5/周奖励/名额 100/四项分值/三档排名奖励/默认奖励），
`season_content.py` 把 `boards` 放宽为可选并新增 `weekly_cap`/`weekly_reward`/`score_values`/`rank_rewards`/
`default_rank_reward` 校验（`_score_map()`/`_rank_rewards()`），`void_frontier_rules.py` 常量与 `reward_for_rank()`
改为内容派生。映射、分值、奖励与赛季窗口（2026-10-15 属 `season.void_frontier:20261007`）均保持原值。
聚焦证据：新增 `test_cross_realm_void_frontier_content.py` 15 passed（三张指令表与记录一致且动作值属于该事件贡献键、
赛季记录与模块常量/分值表/周奖励一致、`reward_for_rank()` 四档与返回独立副本、窗口 id 与天数不变、11 项校验失败用例）；
回归 `test_cross_realm_events.py`/`test_cross_realm_event_snapshot_integrity.py` 29 passed、`test_void_frontier.py` 10 passed。
未跑全量/压测/部署，未验 QQ 真机。

本轮有限任务已完成：`chapter.1.stage.3` 雾中守门与 `chapter.2.stage.1` 城镇委托两关的正文、人物/场景、
可执行目标、来源/奖励/后续引用、失败重试规则及现有战斗/委托、快照、事务、幂等消费者已落地。
沿用本轮已确认的 `19 passed`、`lastfailed={}` 聚焦证据；不重跑全量、不扩展 travel/world，不重开 M9，
不扩 84 关、PvP、支付或跨服。提交 `cdc24ca9e573831f75a0e01f418436de45eb65ba` 已同步
`main`、`develop` 与 `origin`，主线 CI `38151296495` 成功。

- v0.1.6 已正式发布，Release 工作流 `38151749011` 成功；API 已确认 `project.tar.gz`，大小 2361948 bytes，
  SHA-256 为 `3f66fc3430ab4f722a7adb35e23f2aa5e4053aa98b3ceb8276c0fd25ce2d70e2`，旧 tag 未移动/删除。
- `/root/xiu3-qq-test-20261011` 已用自身 `.venv` 从 v0.1.6 Release 更新；直连下载超时后使用安装器既有的
  已验证 Release 代理地址完成下载，未使用源码 git pull。停机备份为 `.xiuxian3/backups/pre-v0.1.6-20261011`，
  自动事务备份为 `deploy-0050b13f13ee43ba99d87871a6348b02`；53 个 JSON 事务内解析通过，仅确证官方
  `剧情/主线.json` 更新，未知/自定义 `奖励/奖励.json` 与 `战斗/遭遇池.json` 保留。
- `.env`、WAL/SHM、用户 data 均保留；SQLite 当前与备份均 `integrity_check=ok`，200 张表及全部表行数一致。
  宿主 venv 从宿主目录检查无 `nonebot-plugin-xiuxian-3` 发行包。
- 实际加载路径为 `/root/xiu3-qq-test-20261011/src/plugins/nonebot_plugin_xiuxian_3/__init__.py`，
  1 matcher/1 handler、重复注册 0；当前 `nb` PID 3587177、bot PID 3587184，
  `127.0.0.1:18094` 监听，QQ READY、Uvicorn/application startup complete，当前日志无 ERROR/Traceback。
  本次未发送真实 QQ 消息、未重跑全量/压测，QQ READY 仅证明连接与启动，不代表真机富消息呈现或权限验收。

- 主线委托历史交付过滤修复已由 `57fcb3480db66304d4a7be2767e04059a8a0e3df` 推送并快进到
  `main`/`develop`；`adventures/repository.py` 现在要求 `commission_delivery` 的
  `delivered_at >= snapshot.started_at`。旧交付与开始后的新交付回归覆盖，主线聚焦测试 `17 passed`
  （未重跑全量/压测）；main CI `38187242470` 成功。
- `v0.1.7` 已在该 SHA 上发布，未移动或删除 `v0.1.6`；Release `project.tar.gz` 下载 HTTP 200、
  归档事务校验通过。`/root/xiu3-qq-test-20261011` 已停机备份后用自身 `.venv` 从 Release 更新，
  备份为 `.xiuxian3/backups/pre-v0.1.7-20261012-082857`，53 个 JSON 保留、种子更新 0、SQLite
  `integrity_check=ok`、`.env` 保留。实际加载路径为
  `src/plugins/nonebot_plugin_xiuxian_3/__init__.py`，验载输出 `matchers=1 handlers=1`，无
  `nonebot-plugin-xiuxian-3` 发行包；当前 PID `3807948`/子进程 `3807956`、端口 `18094`，日志有
  QQ `EventType.READY`、Uvicorn startup 且无 `ERROR/Traceback`。本次未发送真实 QQ 消息。

- `b79e28b` 的 main CI `38135461297`、v0.1.4 工作流 `38135669957` 的 quality 3.11/3.12、
  install-smoke/release 均成功；API 已确认 Release 与 `project.tar.gz`，资产 SHA-256
  `80f81655146bb727bbcc2adce0654b9d188219f84af1b8add7da659b12f5c97e`。
- 首次 v0.1.4 宿主迁移失败：下载器误选 `docker/pyproject.toml`，修正提取后又因旧主线缺正文被严格校验拒绝。
  宿主已停止并备份到 `.xiuxian3/backups/pre-v0.1.4-20261011`；`.env` 和原有 56 个 data 文件字节未变。
- 宿主 53 JSON 中有 6 个差异：主线、引导、技能、材料已与 Git 历史字节级匹配，迁移指纹与来源提交
  登记在 `scripts/seed_migrations.json`。奖励/奖励.json 与战斗/遭遇池.json 无历史字节或 JSON 等价匹配，
  属未知基线，不能当旧官方种子覆盖。已按用户授权仅此测试宿主备份后人工最小合并：灵泉奖池补灵米，
  遭遇池按稳定 key 补缺 desc，保留额外记录、原候选/权重与其他自定义；未加入通用旧官方指纹表。
- Linux/Termux、Windows 和 Docker 共用备份/指纹迁移/事务内 JSON 检查与实际 NoneBot 验载；
  自定义冲突明确失败并恢复源码、TOML 和改动种子。仅源码验载成功后卸载旧 xiu3 pip 发行包。
  依赖准备在部署事务之前，依赖版本不自动回退；运行库和 `.env` 不参与替换。
- 本地最终受影响组 `13 passed in 163.27s`，JUnit `/tmp/xiu3-v015-seed-final.xml`；使用实例自己的
  `.venv/bin/python`，仅借用已准备的本地 pytest 工具，无测试内联网，单 CPU/768 MiB 虚拟内存上限。
  覆盖官方旧主线迁移/重复升级、Docker 共用数据模式、自定义保留/严格冲突回退、坏 JSON 回退、
  指纹表、根目录/单包装归档与 Docker 干扰目录、安装链及文档链接；bash -n、改动 Python 编译与 diff check 通过。
  未做 Windows/Termux 真机或 Docker 实机全测、全量玩法、压测、QQ 消息发送。

- 玄天主线 `chapter.1.stage.1/.2` 既有真实公开行动链保持不变；本轮补齐
  `chapter.1.stage.3` 雾中守门（雾隐探索自动战胜利）与 `chapter.2.stage.1` 城镇委托（稳定委托交付）
  的正文、目标、动作、首通奖励/状态事件、下一关引用和失败重试规则。目标快照由
  `mainline.py` 校验，`repository.py` 从已结算探索/委托记录消费，提前领取保持进行中且不写 operation，
  重复领取沿用幂等回放。后续主线仍未完成内容化验收，不能由本轮两关推断剧情全线完成。
- 离线挂机已有持久化、重启恢复、结算、每日次数/资源上限与幂等实现。本轮只增加 OneBot 短测证明冻结奖励
  在重启后仍可结算、名望按地点上限封顶且回放不重复发放；未新增另一套离线系统。
- PvP 的现有本地战斗/竞技入口不等于完整 PvP 进度合同。本切片不改匹配、赛季、排名或跨服资产；真机平台
  与 PvP 长期进度仍单独待验/待定义，不据此宣称完成。
- M9 的历史完成范围与部署/数据证据见本节下文；它不阻止也不替代当前玩法阶段。

本轮物资/采集来源交付（2026-10-11，`work/m9-content-data`，历史）：

- 材料文件仍为 49 条稳定记录，不新增物品或未来效果。现有 32 个个人配方使用 19 种输入，
  本轮在其中 12 种物资登记 17 条 `gathering_sources`，对应 9 个已实现采集/探索模式，
  29 个配方引用这些物资；引用闭合不等于这 29 个配方均重新公开生产验收。
- 灵泉采集原四个加权结果各追加 1 份粗糙灵米；原灵叶、泉水、阵砂的联合分布保留。
  耗时 90 秒、体力 6、每日 6 次及感气二层/引导准入沿用现行规则。
  新来源由现有 loader → 探索结算 → 同事务背包/operation → 烹饪 → 物品使用消费，
  不是来源文字、夹具发放或尚未提交的新探索模式。
- 新增 `xiuxian/material_content.py` 与 `test/test_material_content.py`。`validate_material_content`
  有意只校验较窄的 `gathering_sources` 矩阵：12 种材料、17 条来源边、9 种模式和 29 个配方消费者；
  这不覆盖所有玩法来源，也不据此判断其他材料缺少来源。独立校验器复用
  已提交探索单参数接口、奖励与配方解析器，拒绝坏名称/desc、模式、奖池、缺产出、
  无配方消费者、重复来源及布尔/小数/非正数量；不改业务接口或数据库。
- 隔离暂存树定向结果：31 passed、9 deselected（仅省去重复 QQ 共享业务参数实例），
  18.91s；JUnit `/tmp/xiu3-material-content-staged-final-20261011.xml`。
  OneBot 公开短链覆盖真实移动、两次采集、故障零写、重启/改值后的旧结果领取、烹饪与使用回放。
  仅缩短境界进度，不注入来源物资。独立导入/签名/来源 smoke 与 diff check 通过。
- 主脏工作树先前同组为 26 passed / 1 failed：保留的未跟踪 `data/战斗/遭遇池.json`
  中 `encounter.xuantian.outskirts` 缺 desc；不能称主工作树全部内容通过，也未改动该文件。
  校验器误调用未提交双参数 API 的 11 个失败已按真实签名修复，全部拒绝断言保留。
- 七种未进入该专用采集矩阵的输入已另行审计确认：`domain_core` 由 `season.domain_war` 兑换；
  `void_anchor`/`void_crystal` 有生效中的虚空材料来源与虚空玩法奖励路径；炼丹/炼器/阵法三种大师作品
  和采矿镐均有 `source_recipe_key`，并已校验对应配方产出。因此它们不属于这 12 种材料的
  `gathering_sources` 校验范围，但不是缺少玩法来源。上述是材料阶段的历史待收口说明；
  M9 随后已完成验证、审查并合入 main，旧“不发版、不部署”限制不覆盖当前用户明确授权的 Release/指定宿主迁移。

| ID | 工作项与明确缺口 | 依赖/验收 | 当前进度 |
|:--|:--|:--|:--|
| M1 | 收口市集/灵兽 operation 修复与 4 处旧战斗夹具修复；保持现有脏改动 | 使用 `/root/myenv/bin/python` 补验相关失败/跳过节点、本域与受影响边界；记录最终树和结果 | 已完成：市集/灵兽/夹具聚焦组 12 passed |
| M2 | 核对已复现的 `items.use` 回放回执篡改：恢复量被伪造为 `ITEM_USED 9999` | 先在隔离库复现当前基线，再限定物品使用回执、事务零写、修复重放、双适配器与共享边界 | 已完成：严格回放校验与双适配器零写/修复重放，`test_items.py` 16 passed |
| M3 | 一次性完成全产品范围对照；逐域列合同、入口、内容生产者/消费者和验收，核实来源/配方/悬赏矩阵、技能成本冷却和其他实际消费缺项 | 对照总表全部功能域及 `content-data-contract.md` 差距表；每个缺项有证据、依赖、目标和验收；来源合同不足转 B1 | 已完成：见下方范围对照冻结表；未把陈旧盘点当作运行时缺陷 |
| M4 | 完成 M3 登记的具体领域交付：玩家链缺口、已定义但未接通功能，内容引用/来源、事务、并发、恢复与适配器闭环 | 依赖先基础后玩法；已闭合能力复用；受影响快测；不臆造规则 | 已完成当前可本地闭合项（M1/M2）；其余需 B1 规则或 B2/B3 外部条件 |
| M5 | 对已实现公开能力取得业务基线一次完整 pytest 与新角色公开成长至渡劫 L10/飞升/留界；审查当前全部相关 code/test/docs/AGENTS，提交并普通 push 到 origin/main | 本次旧双平台全量与等价去重后的最终测试模块按下方证据边界复用；安装/启动/备份恢复按适用范围复用；真实失败最小修复；不发版、不 force、用户数据/密钥/缓存不 stage | 已完成并推送：旧双平台树全量 2308 passed；最终树等价去重、26 项短测及 collect 通过；M5 完成时 main 与 origin/main 同为 `4272066695bae6f52098a390dcabe4a1ffcaf852` |
| M6 | 以首次成功近郊采集作为 `item.manual.sunrise_breath` 的一次性引路嘉奖来源；让文档已有的 QQ AppID 能力配置实际控制 handler Markdown/纯文本降级 | 复用引路任务的已结算来源、主动领取、operation 快照/幂等；QQ 只测配置注入、formatter 与发送段，不验证真机 | 已完成：首采集奖励接入并验证领取/幂等；QQ AppID 配置与纯文本降级接通，聚焦测试通过；无真机/权限呈现结论 |
| M6b | 分类帮助、悬赏条目旁蓝字操作、access_any 结构校验 | 帮助总览/六分类、无固定斜杠；Markdown/纯文本短合同；不更改悬赏结算规则 | 已完成并推送 `06bc711`；12 passed in 8.85s；未验证真机、未接入键盘 |
| M7 | 旧范围内最小来源/引用/消费接线 | 原有限清单、成本/快照/幂等/失败恢复及受影响短测；不等于全部内容域覆盖 | 已完成审查、提交和普通推送：业务提交 `579c3ab277d90eafd9d267693be89e678b533282`，独立远端一致；当时聚焦组通过。用户后续明确纠正其覆盖边界；详见 M9，不能把 M7 作为内容完整证明 |
| M8 | 自然分类帮助与玩法旁蓝字；角色创建/寻仙/资料改名及生产预览的上下文入口；普通 handler 按需 QQ 键盘 | 六分类与原命令保留；待填参数只预填，完整动作才直接发送；配置前缀只入 payload，纯文本可读；身份/幂等/投递重试合同不变；聚焦短测与普通推送 main | 已完成审查与普通推送：`f4f43886e2e004542dadd81039f63b26b4827839`，独立远端一致；最终 29 passed。帮助无按钮网格，创建后寻仙与首次寻仙后阅读各一个完整动作按钮；正文改名/生产/悬赏和按地点引导链接已接通 |
| M9 | 全 manifest data 覆盖：补齐已有本地功能的内容定义与公开来源，统一接入消费者并验证引用闭合 | 保留稳定 key、存档和已接任务快照；地图/悬赏/探索/来源/战斗数据由 loader → application/repository → 玩法消费；随机、快照、幂等和恢复合同不变 | 数据与消费者已完成并合入 `main`：53 个 JSON 文件、42 个内容 kind、33 地点/10 个区域/64 条通路、19 个开放探索模式、34 条悬赏、45 个开放奖励池、55 个敌人/14 个遭遇池、32 个配方/14 个来源；内容完整性校验与受影响聚焦测试通过；M9 合并提交 `9be1cae`，收口文档提交随后推送；CI `38108888614` 与收口文档对应工作流均成功。仅保留 B1–B3 外部边界，不宣称完整产品或真实 QQ 发布 |
| M10 | 闭合普通世界移动的剩余旅行审计：区域有向边作为路线成本/来源准入合同，地点记录裁决状态与内容级门槛；云舟与虚空航道专用行程继续使用各自会话 | 冻结普通/跨域路径、费用/通行物/每日限制、门槛引用及既有 operation/session/snapshot/恢复兼容；普通路径优先于同目标专用航线，缺少普通入边时预览云舟路线及起航地点；专用航线字段必须引用有效地点、物品、境界及任务/引导 | 实现与本地聚焦验收完成，待提交/推送/CI：普通方向路线由区域边唯一裁决，地点状态/共同门槛负责共享限制；旧运行时逐目标费用和通行物已归一到各入边，未知旧零费用地点保持零；云舟/虚空航线分别由 `data/地图/云舟航线.json`、`data/地图/虚空航线.json` 提供，普通路线图从 65 条边收束为 61 条，专用目的地不再伪装普通移动。云舟起航事务消费数据化来源/目标/成本/准入；可选任务门槛同时出现在预览和起航校验。虚空新行程消费数据化耗时/体力/锚费/随机流；新建会话冻结既有快照，完成、operation 重放与恢复不重读当前定义；不改 DB/schema 或既有会话字段。数据来源提交 `8ccde33234cbefa5b89e12253f647d4430d9391a`，区域与内容清单的新旧 SHA-256/provenance 已登记，未知/自定义 seed 仍按迁移守卫保留。诊断：先前缺失解释器的宽命令不计验收；`python3 -m pytest -x` 首个历史断言要求已退役文案“当前状态”，属于过期预期，已改为精确断言“当前终局状态”；随后档案快照用例暴露基础角色无法在 20 回合内结束守卫战的测试夹具缺口，已统一使用既有高战力夹具，未改战斗门槛。验收：world/travel/恢复合同 `77 passed`，运输内容与任务门槛反馈 `9 passed`，虚空档案双适配器/快照/故障恢复 `5 passed`，种子迁移与安装文档 `35 passed`；后续使用正确临时 venv 单独复验安装文档 `27 passed`，系统解释器缺 FastAPI 的尝试不计验收。均为聚焦组，未重跑虚空塔、M9 完整测试、全量或压测。当前仍待代码检查、提交、推送 develop/等待 CI、普通合并 main/核验 main CI |
| B1 | 刻意锁定的未来效果/副本/授权 | 普通已实现物品来源和配方已转 M7；未来效果保持 locked/planned，不自动扩大实现 | 单列范围，不删除、不冒充开放 |
| B2 | 真实 QQ/OneBot 账号、平台权限、按钮 ACK/Markdown/降级与连接验收 | 部署者提供可用账号、权限、设备/连接；记录真实结果；fixture 与模拟 adapter 不替代 | 指定 QQ 测试宿主 READY 已验证；呈现/权限/回调和真实 OneBot 设备仍待验 |
| B3 | P7 外部项：支付提供方、跨服节点、其他真实环境接入与投产授权等 | 已明确且可本地完成的 Web 权限/CSRF/审计、签名与跨服隔离/恢复合同仍归 M4，不借外部条件遗漏；只把确需外部条件的部分留此 | 正式版本 Release 与指定宿主迁移已按本次授权完成；支付/跨服/其他环境投产仍 locked，不自动开放 |

### 4.1 M7 单次分域清单

以下是 M7 当时的有限细分清单，说明旧交付，不是 M9 的完整内容表。M9 新审计已发现此前域间内容深度、公开来源和硬编码规则缺口；以下 M7.6「未发现」结论仅限当时检出的物品定义与旧范围，不再用于裁定全域内容完整。

| ID / 功能组 | 缺口与证据 / 冻结范围 | 来源与消费者 / 依赖 | 进度与验收 |
|:--|:--|:--|:--|
| M7.1 修炼/功法/构筑 | 18 功法均有入道/引路/悬赏奖池来源；技能、体质、装备已有快照消费者。补 mining/cooking 两个辅修选择与入门物资，不新增战斗效果 | 原入道奖励事务；四条辅修大师配方允许这两种辅修，保留原三艺合成路径 | 已实现并定向通过：采矿/烹饪公开入道发放；功法来源与已有成长证据复用，未逐一重新随机领奖 |
| M7.2 探索/悬赏/矿区 | 原缺 `item.permit.cloud_mine`、`item.tool.mining_pickaxe`、`item.tool.mining_pickaxe_t2` 定义/来源及公开 mining。三种历史授权旗标无公开授予 | mining 入道赠基础镐；另有公开登记/基础镐/进阶镐配方；许可使用写入三个既有授权别名，永久解锁准入；保持原筑基门槛、目标、奖励与次数 | 已实现并定向通过：近郊材料公开取得、三种物品生产、仅携带许可准入、永久登记、真实采矿与悬赏领奖；次数/重复登记/坏回执零写与重试 |
| M7.3 生产/配方/经济 | 原 26 个个人生产配方在 Python，JSON 15 条；12 个运行配方无 JSON，`recipe.food.spirit_rice` 有 JSON 无消费者。补 9 大师作品和 `item.void_power_crystal` 定义；32 条规范配方统一为 RecipeDefinition 字段 | JSON 唯一参数 → 同一生产订单；cooking 接米饭/云灵茶。基础配方不依赖矿区产物。作品交现有合道任务；能量晶消费恢复虚力 40、上限封顶/300 秒冷却，虚力未开启零扣除；不扩大委托范围 | 已实现并定向通过：原 26 中 22 完全同值、4 仅扩辅修，70 选择名保留；坏引用拒绝，旧订单改值/关闭重放与冻结领取、生产故障回滚、失败退款、重启/过期恢复；界壁试炼材料 → 能量晶生产/使用 |
| M7.4 灵兽/灵骑/灵具 | 原 `beast.gear.sack_small` 无 recipe、鞍具 vague 来源不执行；现绑定两条 companion 配方。竹鹿主线来源补精确 `story.mainline.xuantian:chapter.1.stage.1` | 近郊木材/铁石/粗糙灵米 → 生产 → 背包扣除 → 唯一灵具实例；本人主线首关公开领取后结缘竹鹿，保留原来源分支 | 已实现并定向通过：装备故障零写/重试、唯一实例/重放；行囊 +5 进入属性/冻结与中文来源说明，摆摊/求购实际消费，耐久失效不改旧快照；鞍具运输体力 -1、结算/重放 |
| M7.5 任务/奖励 | 9 悬赏与 66 奖励记录已有消费者，物品扫描只有 M7.2 三项真实缺引用；两条 `item.*>=数量` 为合同表达式，非物品键 | 原引路/主线/悬赏 owner；矿区悬赏冻结与领取复用，不改次数/奖池/目标 | 已实现并定向通过：access_any 物品/辅修引用拒绝；公开采矿形成新进度、原奖池领取与重放；不把旧夹具当公开来源 |
| M7.6 其他已实现域 | 当时仅按旧范围检查活动/社交/塔/图鉴/地图的物品定义，没有验证各域内容深度或规则数据化 | M9 表 4.2 冻结完整域覆盖；B1 锁定能力和平台/支付/跨服范围仍独立 | 仅作为 M7 历史范围；M9 盘点已发现常规内容、塔规则和社交规则缺口，不以 M7 结果宣称域完整 |

B2 缺真实账号/权限/设备/连接与回调条件，B3 缺支付/跨服/投产条件；仍没有真机或发布结论。

M7 规则选择：新增基础制作仅消耗现有近郊材料、少量精力/灵石，UTC 每日上限与订单期限沿用
生产内核；不设计新随机引擎。许可不为市场交易物，使用后保留永久授权；矿镐只作准入，
不声称新增采矿产量/耐久效果。行囊/鞍具成功领取为背包资产，装备时才生成唯一耐久实例。
原 26 配方除四条大师配方扩充合法辅修外保留参数；旧 JSON 未执行的要求以实际运行基线裁决，
统一到同一数据合同而不保留两份数值表。尚未执行的米饭采用原 JSON 材料/时长/次数，补明确成功参数。

### 4.2 M9 全数据覆盖与冻结依赖

以下表格记录 M9 实施前的内容审计快照：盘点时 `data/内容清单.json` 注册 48 个运行内容文件；
M9 新增区域、探索、来源与遭遇数据后 manifest 为 53 个文件。统计只反映当时的 JSON 定义量，
不单独证明深度、公开取得或运行时消费。表内“缺口”和依赖顺序是实施前证据，不是当前待办；
M9 完成状态及当前收口见第 4 节开头和本节末。M7 的旧范围与 M8 交互历史继续保留。

| 内容域 / 审计时定义 | 实施前审计缺口（历史快照） | 实施前消费边界 | 当时冻结依赖与完成检查 |
|:--|:--|:--|:--|
| 基础注册：境界 10、晋升 11、道途 6、规则 3、资源 8；总计 48 个 manifest 文件 | Realm/path 主键完整；`ContentBundle` 仅通用检查 schema/kind/records/key，缺领域字段和全局引用闭合。资源表是存储/显示映射，不等于全部物资来源矩阵；属性/资源公式仍有硬编码运行资源，不因凑条目扩定义 | progression、player/path、stats、items、economy 与各领域规则加载器 | 先冻结稳定 key、开放 realm/path、数值和存储含义；不加无实际消费者的虚假资源。后续所有跨引用依此验真 |
| 世界/地图：盘点 24 地点、11 探索模式；本轮地图切片为 33 地点、10 区域、64 条通路边 | 盘点时没有显式 world-region-location 与通路图，且 6 个运行地点键缺记录、旧 `DESTINATIONS` 有 JSON 门槛矛盾。地点的探索/遭遇/奖励扩展键仍由后续域定义；本轮不把这些 opaque key 当作已接入消费者。探索耗时/成本/次数/地点/敌人/奖池和开放境界映射仍由 Python 固定，rank 映射止于化神 | `world/rules.py`、`world/cloud_rules.py`、`world/void_rules.py`、`exploration/rules.py`；目前 JSON 新地点不会自动成为可移动/探索目标 | **地图数据与校验已完成本阶段**：区域清单覆盖全部 33 个 location key，64 条有向边端点有效且均有反向边；地点门槛引用的 realm/item/quest-or-guide、旅行物品和 codex entry 均闭合；百草坡/铁木林/玄武岩径/云铁矿区/堕落遗迹及终局地点已登记，原键保留。下一数据依赖为物资/采集/敌人与奖池；消费者尚未接入 |
| 道具、装备、奖励与遭遇：材料 49、丹药 12、凭证 12、功法 19；法器/防具各 879、饰品 108、工具 4；敌人 57、奖励 66、技能 117 | 大量材料缺可证实来源；正式遭遇/普通敌人内容多仍由 Python 定义，敌人 JSON 已按 2026-10 时园/境界扩展至 57（`test_combat_content.py`/`test_m9_content_integrity.py` 钉值同步）。道途装备记录很多但多数没有已证实公开获取路径；动态装备只在少数奖池开放。42 项高阶技能共用一类传承残卷，来源可能过窄 | `items/*`、`combat/rules.py`、`combat/party_rules.py`、`adventures/rules.py`、`reward` 各领域消费；敌人 `reward_refs` 不是通用自动掉落合同 | 先定材料/装备稳定 ID 与用途，再提供合法公开生产者/掉落者；随后补敌人原型、战斗/采集奖池和权重区间。每种新增奖励须能取得并被一个既有消费方实际使用；效果限既有白名单 |
| 道途/修炼/技能/装备养成：功法 19、六道途、体质 5 active + 1 locked、神通 109、道脉 30、成长模板 5、词条 17 | 大多数基础功法有来源但技能残卷通路集中；装备效果槽位和战斗风格受代码白名单约束。多数 path-specific gear 没有来源不是“内容已开放”。未消费体质/召唤效果继续锁定 | `manual_rules.py`、`skill_rules.py`、`equipment_rules.py`、`constitution_rules.py`、`talent_rules.py` | 与物品、境界、奖励依赖同序；先补可执行、现有白名单内的差异化公开路径/构筑选择，再改来源解析。新增效果类型、未来召唤能力列 B1，不假装数据可启用 |
| 生产、生活、经济：配方 35、生活 28（派遣 16、居所 2、作物 2、委托 5、服务 2、路线 1、公共工程 6、闲置路线 4）、拍卖 1 | 生产/采集闭环有空洞；仅止血草/灵叶/时痕草作物、两类居所、一条短途运输，服务类型少；高境界委托复用低阶定义。经济资源 8 不覆盖全部玩家可见资源来源矩阵。时痕草的三大辅修消费已补（2026-10-22 Goal 6：时序护心丹炼丹配方+时序锚定阵阵法配方），`recipe` 生产/消费两端在时序主题上闭合 | `production/rules.py`、`livelihood/rules.py`、`route_rules.py`、`commission_rules.py`、`dispatch_rules.py` 与对应 application/repository | 材料/场所/设施先有合法来源，再补不同用途作物、居所、路线、委托/服务、生产配方和实际消费者；验输入、输出去向、资源闭环、门槛/失败退款 |
| 灵兽灵骑：灵兽 5、蜕变 1 | 现有只有两兽、一骑、一灵兽具、一鞍具；可执行生态、境界/地点来源不足。铁背鼠 `companion.evolution` 来源尚未发现运行中的事件生产者；不同兽类没有覆盖已支持效果用途 | `companions/rules.py` 与 companion repository，绑定位/喂养/运输/装备消费既有类型白名单 | 先有对应生态地点/事件与可重复公开资格，再补不同功能灵兽、灵骑、具装及蜕变边；每条来源需能真实生成，不以 `activity_event` 文本冒充 |
| 任务/悬赏/日常：任务 24、悬赏 34、主线 84、故事 1 | 每个开放境界常规悬赏不足 3 条；境界池/目标类型偏窄。奖励目标快照有基础；候选集随机批次语义已闭合：悬赏榜按玩家/业务日种子展示 3 条稳定合格批次（不合格前置条目不占批次槽），接取项恒在榜，随机接取与榜上同源批次，同日重复查询幂等同批、跨 UTC 日轮换（2026-10-22 Goal 5）。日常首组仅 2 选 2，缺少变体；dispatch 6 中高阶内容少。主线玄天止于金丹，后续线不等同各境界通用冒险 | `adventures/rules.py`、`quests/*`、`daily_quest_rules.py`、`specials/dispatch_rules.py`、`adventures/mainline.py` | 依赖有效材料/敌人/地点/配方；数据先补境界适配、不同目标与结果范围，再扩消费者实现按 realm/准入过滤、持久 offer/刷新批次和奖励快照。只统计真实可产生的进度来源 |
| 秘境、事件、赛季与特色：秘境 4 common、事件 12、赛季 1、普通塔 1、虚空塔 2、虚空敌人 6、图鉴分类 9/条目 240/解锁 8/里程碑 6 | common 秘境只有 4；7 套专用秘境规则与三界塔分段/门槛/次数/奖励已内容化（`data/冒险/秘境专用.json`、`data/特殊/三界塔.json`）。事件按 key 专用处理，不能仅加事件 JSON 变出新玩法。图鉴总数被 156 个挑战楼层生成项拉高；社交配置 3 条，宗门成本/成员上限/仓库/冷却仍硬编码 | `adventures/secret_realm_rules.py`、`events/*_rules.py`、`specials/tower_rules.py`、`specials/void_spire_rules.py`、`specials/codex_*`、`social/*` | 先补基础地点/敌人/奖池，再按通用算法的数据合同补各专用规则和有差异的节点/阶段；事件仍以既有专用 key 为范围。图鉴引用真实地点/敌人/结算；宗门只内容化现有本地规则 |
| 公开外部边界 | 未消费未来效果/付费权益、真实 QQ 呈现与权限、支付、跨服、远端发布条件不属于静态本地内容补全 | B1 锁定未来玩法；B2 平台账号/权限/设备；B3 支付、跨服身份/资产与投产 | 不以它们阻止本地规则，也不新开支付/跨服工作、不部署、不向真实账号发消息 |

M9 实施时采用的冻结数据依赖顺序（保留作审计依据）：① 境界/道途/稳定 key 与资源、物品目录及世界区域/地点/准入；② 地点通路、可取得材料和基础采集/活动来源；③ 敌人原型、遭遇池、掉落/奖励池与战斗技能引用；④ 装备/功法/构筑来源、生产配方/设施、作物/居所/路线/服务/委托及灵兽来源；⑤ 悬赏/日常/派遣/主线/秘境/事件所需地点、目标和奖励候选；⑥ 塔/图鉴/社交对前述记录的引用与内容化既有规则。形成跨域引用环后按 SCC 成组冻结；当时先完成 JSON 定义再接入消费者。已有 stable key、既有存档/任务快照不得重命名或重算。

一致的本地规则选择：普通地图与来源必须是可双向抵达、可从公开玩法取得；不存在许可时不凭空加新许可门槛。悬赏按符合境界/地点的候选集加权抽取一批、每批无重复，读取同批不重抽；随机货币数量与物品数量使用既有整数范围/权重模型并冻结实际结果。任务目标只引用当前公开 operation 能产生的结果。新增装备仅配置现有效果白名单，奖励/配方不发未来能力。逐域保留原规则的成本、配额、失败、快照、回放和幂等语义，若当前没有刷新合同则采用免费、每日一次、无主动付费刷新的本地悬赏批次，次日由业务日自然轮换；在消费阶段再落持久状态，不在数据阶段改变 DB。

数据完成状态：**本地 M9 数据与受影响消费者已完成**。内容清单覆盖、地图区域/地点/通路、悬赏多境界候选与每日刷新种子、探索模式/来源、敌人/遭遇池、奖励池和配方引用均由统一校验器闭合；定向测试覆盖缺失 ID、空池、非法奖励、来源资产、JSON 地图消费者与随机悬赏快照。loader → 公开取得 → application/repository → 玩法消费链保持事务、快照、幂等和恢复语义。B1–B3 仍不混入本地内容缺口，也不构成真实 QQ 或正式 Release 结论。

### 4.3 M5 本地验收结果（2026-10-10）

B1 缺规则/来源、B2 真实平台、B3 外部环境仍阻断完整产品或正式 release，但不阻断
已实现公开能力的本地 M5。既有阻塞清单保留，不能把未跑全量/成长链藏入该清单后结束 goal。

以下 M5 退出条件均已满足：

- 使用 `/root/myenv/bin/python`，业务代码/内容基线完整运行一次全量 pytest 并实际通过；
  记录命令、运行时测试基线、日志、passed/failed/skipped 和未覆盖项，不以局部或历史结果替代。
  用户明确授权本次等价测试去重复用旧双平台全量，最终测试模块不重新全量运行。
- 从新角色通过公开命令成长至渡劫 L10，完成飞升/留界的本地路径验收。全量已覆盖的相同完整链
  直接复用，不重复启动；缺少路径则补明确节点/链，终局注入夹具不替代完整成长。
- 当前有效安装、启动、备份恢复证据按代码/环境与覆盖边界复用；相关变化或未覆盖项按需补验。
- 测试真实失败先诊断，再在当前有限范围最小修复；不得 skip/ignore、删除行为断言、
  降低阈值或改产品规则求通过。修后先定向验证；业务、内容或覆盖路径变化按影响补验，
  未解跨域风险触发新全量。仅改名和移除重复平台迭代、保留全部行为断言的等价测试去重
  以结构核对、collect 和受影响适配器短合同补验，不自动触发两小时全量或完整成长。
- 审查本轮全部相关业务、测试、文档和 AGENTS 改动；按明确文件清单提交并普通推送到
  `origin/main` 成功。不得发版或 force push，不 stage 用户数据、数据库、密钥、日志或缓存。

验收、审查、commit 与 push 均有实际成功证据；M5 goal 已完成。
只更新验收结果文档时补文档门槛，保留未变业务树的全量/成长证据，不再启动同一份长测。
完整产品/正式发布继续受 B1–B3 阻塞，不能随本地 goal 完成而标成全部通过。
无相关代码、证据或条件变化时不重复扫描，不扩展为无限新玩法任务。

## 5. 当前验收证据与局限

- M8 仅修改帮助、角色/生产/悬赏呈现及消息发送合同，命令注册、repository、数据与玩法规则不变。
  19 文件白名单已审查、提交为 `f4f43886e2e004542dadd81039f63b26b4827839`，普通
  `git push origin main` 成功，随后独立 `git ls-remote origin refs/heads/main` 返回同一 SHA，
  核验时工作树干净。入口/状态随后仅记录完成结果；最终文档 HEAD 见本轮 `/tmp` 报告。
  使用 `/root/myenv/bin/python`，最终受影响组 `29 passed in 14.08s`，覆盖六分类/返回/原命令入口，
  一份 OneBot 公开启程→引导→入道→悬赏接取/配方制作短链，QQ 原生 Markdown+keyboard 段、
  空/斜杠/其他前缀（含多前缀配置）、蓝字预填、完整按钮直发/缺参数预填、能力降级、
  handler 身份/去重/投递失败重试与既有引导幂等；文档两项也在此组。JUnit
  `/tmp/xiu3-interaction-final-20261010.xml`，0 failures/errors/skipped；diff check 通过。
  首轮 `3 failed, 26 passed`：旧帮助字符串断言需检查链接消费、寻仙回放原本返回已完成提示，
  以及文本降级误删指令下划线；校准前两项断言并修复降级后 `13 passed`，补验悬赏名称链接后
  得到上述最终组。没有删行为断言或改变成本/奖励/幂等规则。
  仅本地 SDK 结构与模拟发送，QQ 真机呈现、权限、连接及 callback ACK 未验；type=2 命令按钮
  沿用普通消息链，不新增回调结算。未运行全量、完整成长、仿真或压测，未部署/发版。
  runtime 在 finally 关闭，pytest 进程已退出；关闭字节码/pytest 缓存，保护用户配置/数据/缓存与其他服务。
  M7 提交与 M8 最终交付 SHA/独立远端核验见 `/tmp/xiu3-player-interaction-20261010.md`。
- M7 业务/数据/测试与必要领域文档按 32 文件白名单提交为
  `579c3ab277d90eafd9d267693be89e678b533282`，已普通 `git push origin main`，
  独立 `git ls-remote origin refs/heads/main` 与本地一致，核验时工作树干净。
  本页及开发入口随后仅记录交付状态；最终文档提交与远端 SHA 见
  `/tmp/xiu3-data-completion-20261010.md`，不把业务提交 SHA 冒充后续文档 HEAD。
  本轮没有剩余冻结本地项，不自动重新全域扫描或扩展为完整游戏/正式发布结论。
- M7 本地有限清单实现与定向验证完成，使用 `/root/myenv/bin/python`，串行执行且关闭 pytest/字节码缓存。
  核心组（`test_data_completion` 当时 16 项、production/items/endgame_work）`44 passed in 175.44s`；
  边界组（行囊说明/耐久、能量晶、OneBot path/stat、help/content/documentation）
  `26 passed, 10 deselected in 50.00s`；内容/QQ/矿区短合同 `25 passed, 2 deselected in 12.55s`；
  许可成本/次数/重复登记与新增坏引用专项 `7 passed in 10.23s`。筛选只去掉重复 QQ 参数化共享业务；
  QQ 保留 AppID 配置、Markdown 段、蓝字转换与文本降级短合同。各组 0 failed/0 skipped；
  四组共 102 次测试执行，JUnit 去重后为 89 个不同节点；最终文档链接/文案检查另 `2 passed in 0.08s`。
  JUnit `/tmp/xiu3-m7-{core,boundaries,contracts,permit}-20261010.xml` 不提交。
  未启动完整成长、全量、仿真或压测，未测 QQ 真机/权限/按钮 ACK，也无性能结论。
- M7 公开短链只替换积累境界/地点/容量/战斗能力的上下文；材料、许可/矿镐、灵具、烹饪产物、
  主线与矿区悬赏进度、界壁试炼虚空材料均通过真实命令及服务端结算取得，未注入这些资产冒充来源。
  行囊耐久失效测试只修改隔离库的磨损状态。既有大师作品专项保留输入材料夹具，证明生产和合道
  交付，材料来源沿用已有成长证据；不宣称本轮重新无夹具全成长。审查修复行囊属性来源展示标签；
  旧模块删除只移走已迁入 JSON 的配方表，仓内无剩余引用。用户运行库/配置/缓存未修改。
- M5 已提交并普通推送至 `origin/main`；M5 完成时本地 `main` 与远端 `origin/main` 同为
  `4272066695bae6f52098a390dcabe4a1ffcaf852`。随后仅文档收口提交已普通推送，当前本地
  `main` 与远端 `origin/main` 同步。本地没有待提交的 M5 改动。
- 本轮收紧物品使用回放数量的精确整数校验，保留恢复量 9999 的篡改断言，新增布尔/浮点数量拒绝。
  灵兽改名、灵具关闭和蜕变成本变化不再使冻结回执失效；蜕变消耗与原 operation 快照互证。
  修前新增内容变化用例为 5 failed / 1 passed；修后物品、灵兽与市场完整性相关组为 33 passed。
- 审查既有未推提交时复现生产委托 `delivered -> settled` 后原交付/过期恢复 operation 重放失败。
  新增两项修前均失败；修复保持原交付状态、零支付拆分及冻结回执，仍拒绝伪造产物、支付和状态。
  受影响委托/市场/库存锁/生产组 19 passed，最后的委托专项 9 passed；无 skip 或降低断言。
- 07:35 的首份全量因上述审查回归主动中止：235 passed in 384.59s，退出码 2，
  日志 `/tmp/xiuxian3-m5-20261010.N0NIgg/full.log`；不计为最终树全量通过。
  更早的 2295 passed / 4 failed 与失败夹具修后定向通过仍只是历史组合证据。
- 本次实际启动的业务代码/测试/内容树指纹为
  `2fcda77e46180d860e6ab849e509503126caf30ac84f14b4dcd8da908837e7d2`；
  按 Git 已跟踪/未忽略文件清单对业务、测试、data、安装与宿主文件排序后逐文件 SHA-256 再汇总。
  唯一全量于 `2026-10-10T07:47:05+08:00` 启动，会话 `22636` / PID `2428825`；
  日志 `/tmp/xiuxian3-m5-20261010.N0NIgg/final.log`，JUnit 同目录 `final.xml`；结果见下方最终计数。

```bash
set -o pipefail
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' /root/myenv/bin/python -m pytest -q --durations=20 --junitxml=/tmp/xiuxian3-m5-20261010.N0NIgg/final.xml 2>&1 | tee /tmp/xiuxian3-m5-20261010.N0NIgg/final.log
```

- 实际运行的旧成长节点为 `test/test_progression_sources.py::test_qq_and_onebot_can_reach_dao_union_l10_from_new_player`。
  它从创建角色起经 QQ/OneBot 两次相同共享公开命令贯通渡劫 L10；领域核心改由本人创建宗门、三个赛季捐献/
  领奖/兑换获得，保留全部原飞升断言。终局战后以 SQLite backup 分叉同一公开成长所得状态验证
  留界及幂等回放，不注入终局状态，不另跑同一成长长链。
- 唯一业务全量已于 `2026-10-10T07:47:05+08:00` 启动、`2026-10-10T10:02:45+08:00` 左右结束，
  PID `2428825` / 会话 `22636`，实际结果为 `2308 passed, 0 failed, 0 skipped`，耗时
  `8140.27s (2:15:40)`；JUnit `tests=2308, failures=0, errors=0, skipped=0`，耗时
  `8139.888s`。这是旧双平台测试树的实际全量证据，慢节点包含上述完整成长并实际贯通渡劫 L10、
  飞升和留界；日志与 JUnit 仅作本地证据，不 stage。
- 最终测试节点改为 `test/test_progression_sources.py::test_shared_commands_can_reach_tribulation_l10_from_new_player`，
  仅改函数名和把该长节点平台迭代由 QQ/OneBot 两次改为 `qq.official` 一次。
  旧模块 SHA-256 为 `5310dcad76623a1c8a77d869f0fb3742ed4f4e1b6fb3dd3c5f45d10496f80adb`，
  新模块为 `a07095aa322c2ed887701686d6eea9c372959825833036891cda1248853d2af4`。
  父线程 AST 核对全模块等价、229/229 行为断言保留，夹具、命令、预期与两结局未变。
  父线程必要补验：documentation、adapter_normalization、messaging 全文件及两个 SDK 事件到
  shared application 短节点，26 passed in 8.09s；成长模块 `--collect-only`，3 tests collected in 4.23s，
  已收集新共享节点；`git diff --check` 通过。未重新执行完整成长。
  本次全量是旧双平台测试树的实际运行证据；最终测试树只经等价去重与短合同/收集补验，
  不能称最终测试树重新全量通过。未来共享业务长链只跑一份，真实平台仍按 B2 待验。
- 成长链沿用确定性时钟/随机、主角容量 500、辅助角色资产/战斗资质和学徒准备夹具；
  这证明公开命令及持久化路径，不宣称无夹具的自然资源成长、所有来源已闭合或真实平台通过。

### 本轮 M9 地图与部署收口（2026-10-11）

地图区域/地点数据、区域归属、64 条双向通路及门槛/图鉴引用校验已完成；`test/test_world_content.py` 定向 4 passed。独立一键安装宿主 `/tmp/xiu3-onekey-m9-20261011` 使用端口 `18093` 启动并加载 `nonebot_plugin_xiuxian_3`、OneBot V11、QQ，JSON 53 个文件校验通过，日志无 `ERROR`/`Traceback`；QQ 仅做占位配置解析，未连接真实账号。其余 M9 数据与业务改动保持未提交。
- 文档/安装入口与已有留界边界组为 11 passed。安装脚本、打包与宿主入口未改变，按该范围复用。
  本轮隔离 NoneBot smoke 使用 `~fastapi+~httpx+~websockets` 实际加载 QQ/OneBot 和插件，
  重复 runtime 初始化保持 553 个命令、1 个 matcher、1 个恢复任务，关闭后任务已释放；
  日志 `/tmp/xiuxian3-m5-20261010.N0NIgg/startup-smoke-fixed.log`。
  首次 smoke 误用仅 `~fastapi`，因缺 HTTPClient 被 QQ adapter 拒绝；修正 smoke 驱动后通过，未改业务。
  迁移、备份恢复和坏工件原库保护将复用本次全量中的相应专项，不把 smoke 视为真实账号连接。
- 当前 code/test/docs/AGENTS 及 5 个既有提交已审查；上游移植报告已完成；M5 提交和普通
  push 已完成并核对远端。未发版，用户数据、运行库、密钥、日志和缓存未纳入提交。
- M6 首次采集里程碑增加绑定 `item.manual.sunrise_breath` 1；实际本人成功探索结算后任务完成，
  玩家主动领取，重复 operation 回放原结果且不重复发放。验证：
  `test_guidance_quests_use_settled_sources_and_shared_claim_transaction[onebot.v11]` 1 passed。
- `XIUXIAN3_QQ_CAPABILITIES` 现在解析为 AppID 到能力列表的 JSON 映射并由安装 handler 注入；
  QQ 消息事件本身没有 `application_id` 字段，handler 从当前 Bot 的 `self_id` 取 AppID；
  未设置维持历史默认，显式未列能力或未匹配 AppID 走纯文本。普通 handler 确实发送 Markdown
  segment；后续悬赏 `command:` 链接已由 formatter 转蓝字，普通 handler 未接入键盘，键盘是
  独立 keyboard segment 与 Markdown 组合。QQ 配置、消息 formatter 与 OneBot 首采集链的聚焦
  集合（含 QQ 真实 SDK 事件归一化与内容检查）`25 passed in 9.46s`。未测试 QQ 真机呈现、
  AppID 权限或按钮回调 ACK。
- M6b 已普通提交推送 `06bc7119e5650c2024539f16a9c245c4ff3d4f20`，此前独立远端查询一致。
  分类帮助、蓝字转换/降级、QQ 配置、准入结构和奖励冻结/预览 12 passed in 8.85s。
  新蓝字测试替换 segment 构造器，仅证明转换/发送分支；真机与全量事件覆盖不由此推断。
  M7 是用户新授权的有限数据补全；M5 的 2308 只证明旧双平台树，不声称当前代码重新全量。

## 6. 维护与历史

完成任务时只更新本页对应行、验收证据和受影响领域合同。历史材料只解释已做过什么，
不重新参与排序，不覆盖当前产品合同或测试策略：
[状态历史](current-status-history-2026-10-09.md)、
[实施历史](implementation-plan-history-2026-10-09.md)。
[实施计划](implementation-plan.md)只维护有限里程碑、依赖和交付模板；
[完成状态](completion-status.md)只作为本页的交付入口。
