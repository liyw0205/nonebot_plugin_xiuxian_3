# 修仙 3 实施计划

本计划以 `docs/xiuxian3-design.md`、[开发文档总入口](development-guide.md)、`docs/index.md`
和[完整内容开发总表](content-development.md)为产品裁决来源；当前分支的运行时状态以
[当前开发状态](current-status.md)为准。各域 `content-v*.md` 只是历史发布快照，不是并列规范。
历史记录中的内容/规则版本字段已从运行时移除；恢复与回放冻结实际业务数值和结果，不按版本号选择分支。
修仙3是新游戏：旧项目只能提供通用玩法分类和适配器经验，不能决定境界、数值、命令、物品、表结构或业务流程。

当前待办与优先级只由[当前开发状态](current-status.md)第 4 节的唯一切片账本决定。本计划中的编号和历史记录
不构成任务队列，内容快照、稳定键或文档行号也不代表开发先后；每次开始前按[开发指南](development-guide.md)
第 3.3 节横向比较所有未闭合玩家路径，并遵守功能域冷却。体修试炼悬赏曾因孤立奖池而错误重入冒险/战斗域，
该历史记录不构成扩展悬赏玩法的依据。本轮仅因现有领奖快照的重复 JSON 键可篡改实发奖励、且已由 QQ 与 OneBot
公开路径复现，登记为窄范围正确性例外；最近十条切片未触及 `adventures`。v0.1 特色玩法的雾隐试炼塔 1–30 层和 `story.xuantian.road` 三分支
均已通过 QQ 官方与 OneBot V11 验收；雾隐塔已按 v0.2 合同扩至 45 层，三界塔 v0.3 单人 1–20 层和 v0.4 单人 21–40 层现已开放，低层快照和 operation 哈希保持稳定。已验收切片的来源审计与失败恢复继续作为稳定性要求，跨服能力、
Web 写操作和外部支付继续锁定，直至身份、权限、审计与恢复合同通过。
[当前开发状态](current-status.md)是剩余工作的唯一清单。未出现在
[当前开发状态](current-status.md)“已开放”表中的内容，不得被命令、按钮或 Web 写入口当作可用玩法。

## 已闭合切片：市集 operation 结果严格回放

固定摆摊发布、购买、取消和过期的 operation 回放都经过
`xiuxian.economy.repository._market_operation`。该函数已经核对 operation 名称与请求哈希，但仍用
`json.loads` 解析 `operations.result_json`，重复键会静默覆盖；`MarketOrderRecord` 投影还会把布尔或字符串数值强制转换，
没有核验字段集合和金额关系。本条复用 `utils.operations.operation_replay` 严格解码并要求对象结果，再核验精确字段、类型、状态、数量、
手续费与冻结金额的一致性。坏 JSON、重复键、非对象或错误结构在任何本次请求写入前失败；修复账本后同一 operation 可重放，
不重复改变资产、订单、锁、流水或 operation 数量。此缺陷只会伪造回放回执，不会二次扣款或发货。

候选比较：未寻仙角色开始探索的旧错误码观察已被当前阶段检查与 `EXPLORATION_REQUIREMENT_MISSING` 映射否定，不作为缺口；
生产旧过期单被新单遮挡已有 `test/test_production.py` 双适配器覆盖、当前实现已修复，不重开；其他三界副本、高阶资源链缺少
当前规则合同，Web/跨服写操作仍锁定。市集是现有开放玩家入口、仓储缺口直接可复现，经济子插件在最近十条触及一次，
故选择此窄范围切片。只读文档/入口审查由 `/root/doc_audit` 承担；无并行编码，主线拥有
`xiuxian/economy/repository.py`、`test/test_market_operation_integrity.py` 与本计划/状态页。

轮转窗口按实际运行时代码提交复核（不计测试沙箱隔离和测试夹具修复）：`b0e1fa3` economy、`65a12ca` adapters、
`8901393` specials、`68137ad` events、`2aa98d9` progression、`53ccffc` advancement/progression、`367ef2a` social、
`d156b44` world、`3839546` world、`cf301e7` exploration；其中 progression/world 各两次，其余各一次。

不改市集命令、准入、价格/手续费、订单状态机、库存锁、资产/流水结算、operation ID 或其他经济路径；不新增运行时版本标识、
旧格式兼容分支或玩家可见开发文案。验收需用 QQ 官方与 OneBot V11 真实命令覆盖四类 operation 的损坏账本零写、修复后同 operation
重放、重启幂等、不同输入冲突及回执字段校验，并运行市集/库存锁/求购/拍卖相关聚焦回归、文档测试、编译、内容 JSON 与
`git diff --check`。

本条已闭合：`_market_operation` 复用 `operation_replay` 严格解码并由 `MarketOrderRecord` 完成回执与订单投影互证，
发布、购买、取消、过期四类 operation 的坏账本均在任何资产、订单、库存锁、流水或 operation 写入前拒绝；修复后沿原 operation
重试，重启回放保持幂等。`test/test_market_operation_integrity.py` 专项 1 项覆盖 QQ 官方与 OneBot V11、重复键/坏 JSON/非对象/错误类型、
金额与状态不一致、零写、输入冲突、修复重放和重启恢复；市集、库存锁、求购、拍卖和生产聚焦回归共 13 项通过，文档测试 2 项通过，
`compileall`、49 个内容 JSON 严格解析和 `git diff --check` 通过。经济域进入轮转冷却，下一轮重新横向比较全部未闭合玩家路径。
全量回归随后发现 4 项陈旧测试夹具只写入 `body/agility`，在战斗前触发六项资质校验；仅在
`test/test_tribulation_endgame_chain.py` 与 `test/test_void_archive.py` 复用
`test/combat_fixtures.py::BALANCED_QUALIFICATION` 补齐合法资质；全量首轮为 2295 项通过、4 项失败，修复后四项定向回归通过，
连同首轮通过项合计 2299 项覆盖通过。

## 当前唯一切片：灵兽 operation 回放严格互证

公开的 `结缘灵兽`、`喂养灵兽`、`休养灵兽`、`装备灵具` 和 `蜕变灵兽` 都复用
`xiuxian/companions/repository.py::_companion_operation`。此前实现以宽松 `json.loads` 读取 operation 结果，
随后 `_mutation_from_payload` 把历史 payload 直接投影为 `CompanionMutationRecord`，没有精确字段、类型、范围，或玩家/灵兽当前投影互证。
篡改 `operations.result_json` 可让 QQ 官方与 OneBot V11 回放返回伪造经验、状态、消耗或进化结果；不会二次扣资产，但会污染玩家可见回执。

本条复用 `utils.operations.operation_replay` 的严格 JSON 解码，并为灵兽 mutation payload 增加精确结构、类型、状态、数值、动作消耗、实体归属和灵具耐久校验；
坏 JSON、重复键、非对象、布尔/字符串数值、未知字段或最新结果与数据库投影不一致的结果，在回放返回前拒绝且不写新状态。通过 operation 行序号识别同一玩家/灵兽的后续写入，
保留合法状态变化后的历史快照回放；修复账本后原 operation 可重放，重启保持幂等。不改灵兽来源、喂养经验、进化概率/成本、灵具配方、探索发现、运输、战斗快照或玩家可见文案。

候选比较：求购/拍卖属于经济域，市集刚闭合后进入冷却；秘境/跨界事件回放要么已有严格结果合同，要么需要连同战斗快照扩大审计；社交过期只影响
只读投影且仍有时间门槛。灵兽为未触及且有完整公开双适配器入口的功能域，故选择这条窄范围回放正确性缺口。

文件边界：主线独占 `nonebot_plugin_xiuxian_3/xiuxian/companions/repository.py`、新增
`test/test_companion_operation_integrity.py`、本状态页和本计划；只读子代理 `/root/next_path_audit` 负责候选/合同审查，
不修改工作树。专项覆盖 QQ 官方与 OneBot V11 的喂养回放，既有回归覆盖结缘、休养、灵具和蜕变；均验证损坏账本零写、修复重放、输入冲突、重启幂等。

本条已闭合：`_companion_operation` 严格核验 mutation payload 的精确字段、类型、动作消耗、实体归属、最新投影、蜕变阶段与灵具耐久；
同一玩家/灵兽存在后续 operation 时保留旧快照语义。`test/test_companion_operation_integrity.py` 双适配器专项与既有灵兽回归共 67 项通过、4 项因本地缺少 `nonebot` 跳过，
`compileall` 与 `git diff --check` 通过。灵兽域进入轮转冷却，下一轮重新比较全部未闭合开放路径。

## 已闭合切片：闭关快照与结算回放严格互证

横向审查确认 `开始闭关`、`结算闭关`、`恢复闭关` 已由 QQ 官方与 OneBot V11 共用同一 application/repository，
现已在 `AdvancementRepositoryMixin` 统一严格解析闭关快照、会话列、角色归属、冻结奖励和 operation 结果。重复键、
缺字段、错误类型、错误奖励或损坏账本均在玩家状态、闭关状态和 operation 写入前整体拒绝。

范围限定为闭关开始结果、结算/恢复快照和 operation 回放。开始成功后冻结闭关键、开始/结束时间、精力与物品成本、
角色境界/道途快照、随机种子和周期；结算/恢复严格核对快照与会话列、玩家身份、状态、时间窗口和实际奖励。复用
`decode_json_strict`、`spend_player_state`/`change_player_state` 和现有 operation ledger，不改闭关规则、其他养成、
正式 PvE/PvP 或切磋/训练傀儡只读观战。`test/test_retreat_integrity.py` 已覆盖两适配器的重复键、坏快照零写、修复重试和幂等回放。

文件所有权：主线独占实际闭关事务所在的 `xiuxian/progression/cultivation_repository.py`、必要的
`xiuxian/advancement/repository.py` 共享校验、`test/test_retreat_integrity.py`、本计划与状态页；
`/root/open_path_candidates` 只读核对 QQ/OneBot 入口与回放测试，`/root/domain_front_contract_audit` 只读复核字段、事务、恢复与
正式战斗/观战边界，`/root/exploration_fixture_migration` 只读检查共享工具复用点。代理不修改工作树，不扩展到其他 advancement 能力。
固定闭关短句留代码，不增加内容 JSON 字段、运行时版本标识或旧格式兼容分支。下一轮从状态页缺口重新横向比较，
不按本记录顺序重复进入闭关或 advancement 子插件。

## 已闭合切片：师徒关系只读查询与过期状态投影

横向审查确认师徒邀请、接受、拒绝、过期和出师已经有真实 QQ 官方与 OneBot V11 写入路径，但玩家没有查看本人
师徒关系的入口。现有 `mentor_relations` 已保存五种终态/中间态（`invited`、`active`、`graduated`、`rejected`、
`expired`）及双方道号和时间字段；缺口是查询合同没有规定公开字段、排序及过期邀请的只读投影，不能直接复用道侣
查询，也不能把平台用户号或数据库编号展示给玩家。

本条只新增无参数只读命令 `师徒关系`（别名 `我的师徒`、`师门关系`）。查询当前角色作为师傅或徒弟的全部关系，按
`created_at DESC, relation_id DESC` 稳定排序；包含关系号、本人角色、双方道号、状态、邀请时间、截止时间、接受/拒绝时间、
出师时间及已结算师傅贡献。`invited` 且已到截止时间的记录只在返回投影中显示为 `expired`，不得在查询中落库或写入
operation；其余状态按数据库原值返回。无关系返回空列表，不创建 operation。坏状态、身份或时间字段返回可重试的只读错误，
不得静默补默认值或产生写入。

复用 `mentor_relations`、现有玩家投影和共享 application/repository；不新增关系表，不改变邀请/接受/拒绝/过期/出师
状态机，不产生邀请、解除、扣费、奖励、图鉴或战斗状态。固定命令短句留在用例代码，关系状态中文名留在代码，不放入内容
JSON。无运行时版本标识、旧格式兼容分支或玩家可见开发话术。

文件所有权：主线独占 `xiuxian/social/mentor_repository.py`、`mentor_use_cases.py`、`application.py`、适配器注册、
社交合同/状态页及最终整合；`/root/open_path_candidates` 独占新增 `test/test_mentor_relations_query.py`，未修改其他
测试或运行时代码；`/root/domain_front_contract_audit` 只读复核关系字段、权限和适配器边界。专项 10 项、师徒/道侣与社交回归
249 项、适配器/观战/社交回归 48 项通过；`compileall`、93 份内容 JSON 严格解析、无版本标识检查和 `git diff --check` 通过。
查询不写 operation，过期只读投影，坏记录可重试且零写；解除规则另行定义，不在本条扩展。

## 已闭合切片：云舟结算与恢复按冻结快照严格互证

公开入口为 `登上云舟`、`结算云舟` 和 `恢复云舟`，QQ 官方与 OneBot V11 共用同一
application/repository。现有起航会保存完整航线快照，但结算与 24 小时恢复只读取会话列，未校验
`snapshot_json` 与航线、费用、凭证、来源/目的地及当前玩家归属一致；结算 DTO 也对 operation
结果使用宽松类型转换。该缺口可在起航后篡改会话列或快照时复现为错误地点写入，属于公开地点状态正确性问题。

本条只处理云舟抵达和恢复：严格解析并校验冻结快照、会话行、玩家身份、状态、时间窗口和 operation
结果；坏快照、字段不一致、错误归属或损坏账本在玩家位置、会话状态和 operation 写入前整体拒绝，修复
后原 operation 可重试，重启回放不重复写入。继续复用共享玩家状态事务和严格 JSON 工具，不改航线内容、
费用、普通移动、正式 PvE/PvP 结算或切磋/训练傀儡只读观战边界。

文件所有权：`cloud_repository.py` 与新建 `test/test_world_cloud_boat_integrity.py` 由
`/root/open_path_candidates` 独占实现；主线负责本计划、状态页、边界整合和最终验收。`/root/domain_front_contract_audit`
只读核对快照字段、事务不变量和适配器覆盖，不修改工作树。测试必须覆盖两种真实适配器的正常抵达、24 小时恢复、
坏快照零写、修复重试、operation 损坏/输入冲突、重启幂等及故障回滚。

候选比较：师徒本人关系列表仍缺状态集合、展示字段和只读过期投影合同；领域前线、功法来源和灵兽行囊配方
也分别缺完整内容合同，均不臆造入口。云舟属于已有开放入口且合同完整的世界域，最近一次世界切片已被多个
其他领域挤出窗口，本条不重复设计普通移动或航线规则。

验收：`test/test_world_cloud_routes.py` 8 项、`test/test_world_cloud_boat_integrity.py` 5 项及世界/引导回归
20 项通过；覆盖 QQ 官方与 OneBot V11 的正常抵达、24 小时恢复、重复/损坏 JSON、快照与会话列不一致、起航/抵达/恢复
operation 篡改、跨阶段回放、故障回滚与原 operation 重试。源码与测试 `compileall`、`git diff --check` 通过。
云舟费用、航线内容、普通移动、正式 PvE/PvP 及切磋/训练傀儡只读观战边界未改；不新增运行时版本标识或旧格式兼容分支。

## 已闭合切片：虚空前线周任务箱严格结算

开工证据：QQ 官方与 OneBot V11 的 `领取虚空前线周任务` 都读取
`void_frontier_weekly_rewards.reward_json`。原实现使用宽松 JSON 解码，重复 `void_merit` 键、字符串数值或缺字段会被静默接受，
可把冻结的 20 点虚空功勋改成 999 并写入玩家状态；该缺陷直接破坏资产完整性，属于 `events` 最近十条触及两次后的正确性例外。

范围只限周任务箱的领取、赛季结束后的待领取转换，以及对应 `event.void_frontier.weekly.claim` operation 回放：复用
`utils.json_cache.decode_json_strict`、`utils.player.grant_player_state` 和现有 `BEGIN IMMEDIATE` 事务；周箱奖励必须精确匹配当前规则的
20 点虚空功勋与 10 点联盟积分，重复键、坏类型、缺字段、坏 operation 结果均在玩家数值、箱状态和 operation 写入前拒绝。修复后沿
原 operation 重试，成功重放不重复结算。赛季榜、正式 PvE/PvP 结算、切磋/训练傀儡只读观战、跨服匹配与身份/资产转移不在本条。

文件所有权：主线独占 `xiuxian/events/void_frontier_repository.py`、`void_frontier_rules.py` 及本计划/状态页；
`/root/adapter_gap_audit` 独占 `test/test_void_frontier.py` 的新增专项，覆盖 QQ 官方与 OneBot V11、坏快照零写、账本故障回滚、
重启后损坏 operation 拒绝及修复重放；`/root/adapter_audit` 只读核对仓储事务边界和候选冷却，未修改工作树。主线统一合并并负责最终验收。

候选比较：师徒关系列表没有查询入口且状态/过期投影合同不全；`item.manual.sunrise_breath` 没有真实来源合同；
`beast.gear.sack_small` 仍缺配方、成本和生产入口；生产恢复遮挡问题已有双适配器专项；未开放副本、Web 写入和跨服身份/资产操作前置不足，
均不选。最近十条代码切片以 `cef0af4` 为止触及 `events` 两次、`player`/`progression` 各两次，其他候选领域要么冷却要么合同不完整；本条仅因公开
资产篡改证据例外重入 `events`，不扩大到其他周箱或赛季领奖。

## 已闭合切片：跨服宗门战奖励箱严格恢复

开工证据：`分配跨服宗门战奖励` 已有 QQ 官方与 OneBot V11 共用的公开命令入口，但公共奖励箱的
`reward_json`、`distributed_json`、成员周奖励和 operation 结果仍使用宽松 JSON 解码。重复键、字符串或负数、
缺字段及奖励与已分配数量不一致时，可能扩大可分配虚空晶，或把坏账本带入领取和过期自动发放。

本轮只处理跨服宗门战公共奖励箱分配、成员周奖励领取/自动发放及对应 operation 回放。复用
`utils.json_cache.decode_json_strict`、共享角色资产/数值事务和现有 `BEGIN IMMEDIATE`；严格互证冻结奖励总量、已分配数量、
轮次/宗门/成员归属、状态与 operation 结果。坏记录在资产、奖励箱、分配记录和 operation 写入前整体拒绝；修复后原 operation 可重试，
成功结果在重启后只回放一次。

文件所有权：主线独占 `xiuxian/social/sect_war_cross_server_repository.py`、相关共享校验及本计划/状态页；
`/root/adapter_gap_audit` 独占 `test/test_sect_war_cross_server_reward_box_integrity.py`，覆盖 QQ 官方与 OneBot V11 的真实分配/领取命令、重复键/坏类型/缺字段/
超发快照零写、operation 插入故障回滚、修复后原 operation 重试、runtime 重建幂等回放和过期自动发放；`/root/adapter_audit/mentor_audit` 独占
`test/test_sect_war_cross_server_json_contract.py`，覆盖奖励箱与 operation 结果结构；`/root/adapter_audit` 只读核对适配器边界和师徒列表候选。
主线完成最终整合与验收。

明确排除：不改报名、积分来源、战争机关、跨服匹配、身份合并、玩家间资产转移、其他社交关系查询、正式 PvP/PvE 结算，
切磋与训练傀儡仍为只读观战，不产生邀请、状态、扣费、奖励或图鉴写入；不新增运行时版本标识、旧格式兼容分支或玩家可见开发文案。

候选比较：师徒关系查询缺状态集合、展示字段和纯只读过期投影合同；`item.manual.sunrise_breath` 缺真实来源；
`beast.gear.sack_small` 缺配方、成本和生产入口；未开放跨服匹配和 Web 写入缺权限、审计、隔离与恢复前置，均暂缓。

验收：跨服宗门战基础流程 2 项、JSON 合同 3 项、双适配器奖励箱与恢复专项 20 项通过；相关社交、适配器、观战与正式战斗回归 49 项通过，
源码与新增测试 `compileall`、`git diff --check` 通过。手动领取写入周奖励行的 operation 引用，已成功分配的 operation 先按分配账本回放，不因后来损坏的奖励箱快照重复发放。
不新增运行时版本标识、旧格式兼容分支或玩家可见开发文案。

## 已闭合切片：探索遭遇奖励按冻结结果结算

入口为公开的 `开始探索` / `结算探索`，QQ 官方与 OneBot V11 共用探索 application 和 repository。`ExplorationRepositoryMixin._settle_exploration_once`
严格读取开始快照并把胜利、战败奖励副本写入待结算 `result_json`；后续 `_settle_exploration_combat_once` 却以宽松 JSON 读取该副本，直接据此发奖，未与开始快照中的冻结结果互证。重复键或副本与快照不一致可改变实际所得。领域合同要求胜利只发开始时冻结的奖励、失败不发探索奖励，且必须关联已结算正式 `BattleSession`。

本条只收紧正式探索遭遇的第二阶段结算：严格解码开始快照、待结算结果及正式战斗结果；校验探索会话、战斗归属/终态、被冻结胜负奖励与待结算副本一致；坏记录在资产、角色数值、会话、图鉴和 operation 写入前拒绝。修复后可用原 operation 重试；成功结果重启只回放一次。复用 `decode_json_strict`、`grant_player_reward`、既有事务和 operation ledger，不改奖池、敌人、自动回合规则或其他探索模式。

文件所有权：主线独占 `xiuxian/exploration/repository.py`、本计划/状态页及最终整合；`/root/adventure_path_audit` 独占新建 `test/test_exploration_integrity.py`，只覆盖 QQ 官方与 OneBot V11 的损坏待结算奖励副本、零写、原 operation 修复重试、账本/快照不一致、故障回滚和 runtime 重建回放；`/root/exploration_transaction_review` 只读核对会话/战斗/快照不变量、operation-first 回放及事务原子性。代理不得修改运行时代码、其他测试或文档，主线负责最终验证。

候选比较：云舟恢复也缺快照与账本互证，但影响的是地点结算，合同及优先级低于直接决定资产发放的探索奖励；经济、生活、生产审查未发现新可复现缺口。`exploration` 不在最近十条代码切片中；近期 `adventures` 一次、`combat` 一次，均未触发子插件两次冷却。`events` 三次、`player` 两次，按冷却暂缓；不因同属大型领域而重做已闭合的悬赏、普通移动、战斗或观战流程。专项 `test/test_exploration_integrity.py` 的 12 项双适配器篡改、修复与恢复测试通过；主线聚焦组共 24 项通过；完整探索专项回归 118 项通过。回归中暴露的旧测试夹具未写完整六项资质或依赖非法高资质，已迁移为合法六项资质并用测试武器保留胜负控制。文档测试、`compileall`、内容 JSON 解析和 `git diff --check` 均通过，本条已闭合。下一轮先补师徒关系查询合同；领域前线活动合同继续只读审查，不直接创建新入口。

明确排除：不改正式 PvP/PvE 战斗规则和奖励，不改切磋、训练傀儡或竞技观战；后两者仍只读，不产生邀请、状态变化、成本、奖励或图鉴写入。正式 PvE/PvP 结算保持正常。不增加运行时版本标识、旧格式兼容分支或玩家可见开发话术。

## 已闭合切片：派遣成本不得侵占交易预留物

QQ 官方与 OneBot V11 均可复现：角色持有 2 个木材，先用 `发布摆摊 item.mat.wood 2 100`
将其全部预留，再预览并接受 `dispatch.workshop_help`（成本为木材 2）。预览仍显示可接，接受后背包
归零，但摆摊仍为 `listed` 且锁量为 2，买家购买随后因实物不足失败。派遣合同已有完整成本，
`specials` 最近十条切片只触及一次；这是资产正确性缺陷，不扩展派遣玩法。

实现边界：新增 `utils.assets.player_available_item_amount`，以背包总量扣除三类交易锁，结果最低为零；
`dispatch_repository.py::_dispatch_preview` 使用该共享读取，接受用例在同一 `BEGIN IMMEDIATE` 事务中复查预检后
才能扣费和创建派遣。
主线拥有 `xiuxian/specials/dispatch_repository.py`、`xiuxian/utils/assets.py`、`xiuxian/utils/__init__.py`、
`test/test_utils.py` 及本计划/状态页。`/root/shared_cost_gap` 独占新增
`test/test_dispatch_reserved_inventory.py`，覆盖 QQ 官方与 OneBot V11 的公开适配器路径、资产与订单锁
不变、拒绝不落 operation/assignment、取消摊单后以原 operation 重试、可用余量恰好够成本时保留锁定库存、成功后
重启重放不重复扣除；不编辑其他文件。`manual_source_contract`、`shared_cost_gap`、`unclosed_candidate_scan` 和
`adapter_open_path_audit` 分别只读核对来源合同、共享成本复用、轮转候选及适配器边界；主线完成实现与整合。

候选比较（开工前记录）：师徒本人关系查询虽已列为缺口，但列表状态/字段及过期邀请投影仍缺合同；领域前线的当前快照合同也未闭合，
先补合同。`sunrise_breath` 无来源合同、灵兽行囊无配方合同、后续秘境及 Web/跨服写入前置未齐，保持关闭；道途、活动、悬赏、修炼、移动、
适配器、虚空塔、生产与服务订单近期切片已闭合，不重入。切磋和训练傀儡保持只读观战，正式 PvP/PvE 结算不变。
最近十条代码切片为 `7de4df0`（player）、`e1b5459`（player）、`afabb94`（events）、`8775c7b`（adventures）、
`d8a040b`（progression）、`f6dd8e6`（world）、`a6df3e1`（adapters）、`f733734`（specials）、
`27f527c`（production）、`1b74cc3`（livelihood）；`2360b13` 仅为测试提交，不计切片。`player` 两次且最近五条
重复，冷却；`specials` 一次，不在冷却。

验收：新增专项在 QQ 官方与 OneBot V11 覆盖预览/接受拒绝、无资产/operation/assignment 写入、解锁后原 operation
重试、可用余量扣费后锁定库存仍在及 runtime 重建重放；工具测试覆盖市场、求购和拍卖三类锁。专项与工具测试 77 项、
派遣内容及交易锁回归 15 项、只读观战/正式战斗回归 8 项、文档测试 2 项通过；`compileall`、全部内容 JSON 严格解析和
`git diff --check` 通过。不改成本/奖励内容、市场生命周期、其他派遣流程或正式 PvP/PvE；切磋和训练傀儡仍只读观战。

## 已闭合切片：道途与辅修内容合同、入道解析和状态展示统一

本轮选择角色域 `player.enter_cultivation` 的内容消费缺口。现有 QQ 官方、OneBot V11 和共享 application/repository
路径已经能完成入道，但 `player/path_rules.py`、`player/cultivation_use_cases.py` 与 `player/use_cases.py` 分别维护
道途/辅修名称和别名；`data/道途/道途.json` 只有道途名称，辅修奖励仍是无名称的 Python 可解释映射。范围限定为：
道途记录的名称/别名、辅修子记录及奖励引用；共享 `ContentBundle` 解析；入道参数解析、成功回执、`我的状态` 展示；坏内容和
锁定/歧义选择的零写拒绝；QQ 官方与 OneBot V11 的成功、冲突、重放和重启回放。仓储继续保存稳定 key，复用既有奖励、图鉴、
operation 事务，不改奖励数值、道途效果、领域选择/切换、生产规则、正式 PvP/PvE 或切磋/训练傀儡只读边界，不加运行时版本标识、
旧格式兼容分支或玩家可见开发话术。

文件所有权：`/root/next_slice_scan` 仅修改 `data/道途/道途.json` 与 `xiuxian/player/path_rules.py`，负责内容字段和纯规则解析；
主线独占 `xiuxian/player/cultivation_use_cases.py`、`xiuxian/player/use_cases.py`、道途/角色专项测试和本计划/状态页。
`/root/path_contract_impl` 只读核对仓储 operation-first 回放、锁定过滤、事务边界和适配器缺口，不编辑工作树。
候选比较已重新核对：生产恢复、经济库存和日课/悬赏/修炼等近期切片均处于冷却或已闭合；灵兽行囊缺真实来源/配方合同，
魔渊深层、其他三界副本和 Web/跨服写入口前置不完整，暂缓。本道途切片是现有公开入口的内容合同缺口，不扩大到道途战斗或切换。

验收要求：临时内容可改变道途/辅修名称并新增别名，两个适配器均能按稳定 key、名称或别名入道；`我的状态` 与入道回执使用
当前内容名称而持久化稳定 key；锁定、歧义、错误类型、缺字段、坏奖励引用、主道途误带辅修和辅修缺选项均零写；成功 operation
同输入重放与重启只返回原结果，不重复灵石、背包、图鉴。内容关闭/改名后的历史 operation 语义由现有 operation-first 仓储保持，
若应用层无法在旧输入下抵达账本则测试明确拒绝，不增加兼容分支。

实现与验收：`data/道途/道途.json` 增加道途/辅修名称、别名和辅修入门奖励记录；`path_rules.py` 负责领域内容校验，
`cultivation_use_cases.py` 与 `player/use_cases.py` 统一入道和状态展示。专项 `test/test_path_content.py` 8 项，
关联聚焦回归 95 项通过；`compileall`、全量内容 JSON 严格解析与 `git diff --check` 通过。提交为 `e1b5459`，
已推送 `origin/main`。道途战斗效果、领域切换和独立辅修入口仍不在本条。

## 已闭合切片：道途选择词移出内容后的 operation 回放

入口是 QQ 官方与 OneBot V11 共用的 `CultivationApplication.enter_cultivation`。以「选择道途 百艺 阵法」入道后移除别名，
原选择词和 `operation_id` 重试曾在两种适配器都返回 `INVALID_PATH`，没有回到已提交结果。现有账本在内容错误返回前核对；
结果冻结原始选择词，同一原请求或当前解析为相同稳定键的请求回放首次结果，其他输入冲突。没有历史 operation 的请求仍须
符合当前内容，移除别名不会留下兼容入口。

主线负责 `xiuxian/player/cultivation_use_cases.py`、`xiuxian/progression/cultivation_repository.py` 和内容/状态/实施文档。
`/root/path_alias_replay_test` 独占 `test/test_path_alias_replay.py`；`/root/adapter_test_scan` 独占
`test/test_path_alias_real_events.py`，后者复用 QQ 官方和 OneBot V11 原始群事件 fixture，验证消息归一化、同事件 operation ID、
重启后移除别名及原事件重放。`/root/candidate_audit` 比较候选和轮转窗口，`/root/reuse_scan` 审查共享工具，
`/root/docs_rotation_check` 核对文档事实，均只读且未改运行时代码。

聚焦 `test/test_path_alias_replay.py`、`test/test_path_content.py` 和 adapter simulation 过滤集共 13 项通过（20 项未选）；
真实事件专项 2 项、文档与无运行时版本标识测试 5 项通过。源码及新增测试 `compileall`、全部内容 JSON 严格解析、
`git diff --check` 通过。未运行整仓全量测试或 NoneBot transport 启动集成。

### 轮转与候选留档

最近十条已闭合代码切片，不计纯文档提交；同一提交允许涉及多个子插件。适配器列记录该切片的入口/测试路径，不表示每条都改写适配器。

| 提交 | 玩家领域/能力 | 子插件与仓储 | 适配器路径 |
|:--|:--|:--|:--|
| `7de4df0` | 道途选择词 operation 回放 | `player/cultivation_use_cases.py`、`progression/cultivation_repository.py` | QQ 官方、OneBot V11 |
| `e1b5459` | 道途/辅修内容与入道选择 | `player/path_rules.py`、`player/cultivation_use_cases.py` | QQ 官方、OneBot V11 共用 application 测试 |
| `afabb94` | 日课领奖恢复 | `events/daily_quest_repository.py` | QQ 官方、OneBot V11 |
| `8775c7b` | 悬赏领奖恢复 | `adventures/repository.py` | QQ 官方、OneBot V11 |
| `d8a040b` | 修炼快照结算 | `progression/cultivation_repository.py` | QQ 官方、OneBot V11 领域入口 |
| `f6dd8e6` | 普通世界行程恢复 | `world/travel_repository.py` | QQ 官方、OneBot V11 |
| `a6df3e1` | 命令门禁与共享路由 | `adapters/base.py`、`adapters/events.py`、`adapters/nonebot.py`、`adapters/onebot.py`、`adapters/qq.py` | QQ 官方、OneBot V11 真实事件 |
| `f733734` | 虚空塔领奖恢复 | `specials/void_spire_repository.py` | QQ 官方、OneBot V11 |
| `27f527c` | 生产快照恢复 | `production/contract_repository.py`、`production/repository.py` | QQ 官方、OneBot V11 |
| `1b74cc3` | 服务订单结算恢复 | `livelihood/service_repository.py` | QQ 官方、OneBot V11 |

最近十条窗口中 `player` 两次、其余各一次；最近五条 `player` 重复。`specials` 一次，未触发子插件冷却。
`2360b13` 是测试提交，不进入代码切片窗口。其他候选比较如下：

| 候选 | 入口与缺口证据 | 合同、复用、轮转 | 处理 |
|:--|:--|:--|:--|
| 派遣扣除交易预留库存 | QQ/OneBot 先上架 2 个木材，再接受消耗木材 2 的作坊派遣，交易锁仍在而背包归零 | 派遣成本合同完整；`specials` 十条仅一次；共享预留锁查询可复用 | 已闭合；预检按可用余额拒绝，并验证原 operation 可重试 |
| 师徒本人关系列表 | 领域说明点名缺查询入口，现有 application/repository 无读取用例 | 社交未在近十条，但状态集合、字段及过期邀请投影需先补合同 | 暂缓；不据不完整合同臆造返回行为 |
| 领域前线快照内容合同 | `开始领域战` 已有运行入口，开工时快照字段与内容闭合不足 | 活动规则合同已补齐并由严格解析器、轮次/赛季快照和聚焦测试验证 | 已闭合；历史候选记录 |
| 道途原选择词 operation 回放 | `CultivationApplication.enter_cultivation`；真实 QQ/OneBot 事件移除别名后无法重放 | `player` 域最近两条连续切片，属于真实幂等恢复缺陷例外 | 已闭合；不改奖励或战斗 |
| 社交过期投影 | `partner_repository.py` 接受分支及 `sect_repository.py` 审批/撤回分支写 `expired` 后抛错回滚；`test_partner_expiry_and_pair_cooldown` 只验过期拒绝 | 时间门槛仍拒绝过期动作；未发现资产/权限阻断，社交生命周期已有切片 | 暂缓，不扩成社交重构 |
| 功法来源 | `data/道具/功法.json` 中 `item.manual.sunrise_breath` 无取得来源 | 缺玩家来源、准入、成本、概率、奖励及绑定合同；消费规则已由 `manual_rules` 共用 | 先补领域合同，不编造奖池/入口 |
| 灵兽小型行囊 | `data/灵兽/灵兽.json` 的 `beast.gear.sack_small` 为 `pending_recipe_key`；现有装备测试直接写背包 | 缺配方键、材料、成本和真实生产入口 | 保持不可取得，先补合同 |
| 观战与正式 PvP/PvE | `test/test_spar_interactions.py`、`test/test_arena.py`、`test/test_party_combat.py` 覆盖只读观战及正式结算 | 两适配器均有专项覆盖；未发现可复现缺陷 | 不重复开发 |
| 未开放副本、Web/跨服写入 | 状态页中对应入口仍为 `partial`/`locked` | 前置、规则或权限/审计/恢复合同未闭合 | 保持关闭 |
| 共享工具整理 | `utils.assets` 已集中三类交易锁；派遣遗漏交易预留的具体缺口见当前状态页 | 不把单一调用方缺陷扩大为所有领域的扣费重构 | 不单独切片；仅接入派遣预检 |

派遣预留库存缺陷优先于上述合同缺口与低影响状态投影，因为它已由两个真实适配器复现并直接破坏已成交交易的资产约束。

## 已闭合切片：日课领奖快照与 operation 严格回放

本轮选择 `每日修行` / `领取日课嘉奖` 的日课轮次领奖恢复。只读审计已在 QQ 官方与 OneBot V11
公开 dispatch 路径复现：`daily_task_rounds.snapshot_json` 的奖励对象使用宽松 JSON 解码，重复
`spirit_stones` 键可以把冻结奖励从 50 改成 999 并实际入账。该路径已有完整轮次、来源投影、领奖、
operation 和回滚合同，且问题影响玩家资产，符合冷却期内的正确性例外；只补来源持久化 JSON 完整性校验，不改变日课来源投影规则。

文件职责：`/root/adapter_gap_scan` 实现 `xiuxian/events/daily_quest_repository.py` 的严格校验；
`/root/path_contract_impl` 补充 `test/test_daily_tasks.py` 的双适配器损坏快照、operation、终态及元数据恢复用例，并只读复核
operation 回放；`/root/next_slice_scan` 只读比较下一轮候选。主线负责本计划、当前状态、共享边界审阅和最终验收。
实现只复用 `utils.json_cache.decode_json_strict`、operation 回放和共享角色奖励事务，严格校验轮次/任务/
领奖 operation 结果的 JSON、字段、玩家归属和终态；来源 operation 与正式战斗结果也严格解码，不改变来源匹配规则。
坏记录在资产、轮次、任务、图鉴和 operation 写入前拒绝，
修复后原 operation 可重试，成功结果重启只回放一次。不得改任务选择、目标、奖励数值、来源规则、正式 PvP/PvE
结算或切磋/训练傀儡只读边界，不添加运行时版本标识、旧格式兼容分支或玩家可见开发文案。

日课专项 20 项、日课/文档/版本标识/奖励/通用工具关联测试 320 项通过；源码与测试 `compileall`、内容 JSON
解析及 `git diff --check` 完成。未运行整仓全量测试或 NoneBot 消息级 transport 集成测试。

候选比较：下一轮可重新评估道途名称/别名内容合同；只读盘点发现 `player/path_rules.py` 与 `player/use_cases.py`
仍硬编码首要/辅修道途名称，而 `data/道途/道途.json` 缺少别名合同，尚需补辅修来源结构和双适配器快照验收；不在本轮顺带实现。
灵兽灵具缺少真实配方来源合同，魔渊深层和其他三界多人副本缺完整探索/战斗/失败/奖励合同，均继续关闭；Web/跨服写入口前置未齐。

## 已闭合切片：悬赏领奖快照与 operation 严格回放

入口为 `悬赏榜`、`接取悬赏`、`领取悬赏`；拥有者为 `xiuxian/adventures` 领域仓储。QQ 官方与 OneBot V11
的公开领奖均已复现：`bounty_offers.snapshot_json.reward` 中重复 `spirit_stones` 键被普通 JSON 解码静默覆盖，
导致被冻结的奖励变成 999 灵石并真实入账。合同要求接取快照决定唯一奖励，损坏快照不得留下任何资产、图鉴、悬赏状态或
operation 写入。范围仅含悬赏冻结快照和 `bounty.claim` operation 结果的严格 JSON/字段/归属校验、零写拒绝及原请求恢复；
复用 `utils.json_cache.decode_json_strict`、`utils.operations.operation_replay` 和 `utils.player` 奖励事务。
领奖进度必须不超过冻结目标，已领奖结果必须恰好达标；过期结果和重放在两个适配器入口均验证不改写玩家状态。

候选比较：生活域与 `events` 在最近十条各触及两次，按子插件冷却暂缓；生产、特色玩法、普通移动、修炼与虚空塔刚完成切片，
暂不重入。共享属性状态页仍标为待独立闭合，但最近已有属性/普通战斗构筑同源切片，状态与实施记录不一致，先只读核对其剩余
合同缺口，不以泛化重构扩大本轮范围。日课现有入口与领奖恢复已覆盖，审查未发现同等级资产复现；悬赏矩阵扩展、其他三界副本、
魔渊深层缺少完整现行合同，保持关闭；Web 写入口与跨服写入继续锁定。

文件所有权：主线独占 `nonebot_plugin_xiuxian_3/xiuxian/adventures/repository.py`、领域合同及状态/计划文档；
`/root/candidate_bounty` 独占 `test/test_adventures_bounty_settlement.py`，只补公开双适配器下的重复快照键、零写拒绝、修复后同 operation
重试/幂等、operation/offer 结果损坏和过期结果重放测试；`/root/candidate_domains`、`/root/cooldown_map` 只读复核未闭合候选与最近十条冷却，
`/root/candidate_bounty` 的原始缺陷复现只读完成。主线统一整合并负责端到端验收。不得改悬赏目标/奖池/次数、悬赏矩阵、战斗或探索结算，
也不得碰正式 PvP/PvE 结算与切磋/训练傀儡只读边界；不加版本标识、兼容分支或玩家可见开发话术。

悬赏与冒险回归 21 项、内容/通用 JSON 85 项、切磋/正式战斗/竞技回归 20 项通过；源码和测试 compileall 及差异检查通过。
未运行整仓全量测试或 NoneBot 消息级 transport 集成测试。

## 已闭合切片：修炼结算与过期恢复快照完整性

开工复现：QQ 官方与 OneBot V11 的 `开始修炼`、`结算修炼`、`恢复修炼` 统一经 progression application/repository。
原实现以 `_json_object` 宽松读取 `cultivation_sessions.snapshot_json`，再将 `base_cultivation`、倍率及神魂增量直接提交；重复
JSON 键可改变实际收益。修为无上限转换，坏快照可能永久跨越晋层门槛；开始前未严格校验资质字段，还可能先扣资源再形成无法结算的会话。
既有流程具备同 operation 幂等与过期恢复，但没有会话快照完整性及双适配器零写验收。

范围仅含普通修炼会话快照及其开始/取消、正常结算、过期标记/恢复和对应 operation：开始前严格验证资质与待冻结字段，避免坏
快照先扣资源；快照数值、玩家/会话归属、模式成本/持续时间、开始请求摘要和终态结果需与会话列及 operation 相符。坏 JSON、重复键、
缺字段、布尔/字符串/小数/负数或语义不一致必须在退款、修为/神魂变化、会话状态和 operation 写入前拒绝；修复后原 operation 可重试，
成功结果重启后不重复结算。复用 `utils.json_cache.decode_json_strict` 与共享角色状态事务。不改内容规则、倍率、门槛、成本、奖励、
突破/恢复状态或正式战斗。正式 PvP/PvE 正常结算；切磋与训练傀儡保持只读，不创建邀请、状态变化、成本、奖励或图鉴写入。

最近十条非文档玩法提交为 `f6dd8e6`、`a6df3e1`、`f733734`、`27f527c`、`1b74cc3`、`cc66276`、
`242409b`、`f21d425`、`e97340b`、`4535eca`；`05d4efe` 师徒出师是第十一条，`8c7ceca` 仅改文档，不计入。
其中 `livelihood` 与 `events` 各触及两次，按冷却暂缓；`specials`、`world`、`adapters`、`production`、`advancement`、
`routine` 近期已有切片；`social`、`progression/cultivation` 未触及。悬赏快照同样有重复键资产风险，但影响面低于
核心修为与神魂，保留为后续 adventures 正确性候选；日课与社交/PvP审查未发现更高优先级的可复现缺口。其他三界副本合同未闭合，
Web/跨服写入口前置未齐，均保持关闭。

实现记录：会话快照、开始 operation、过期标记和终态结果均严格解码；新建前验证资质键与类型，正常结算、恢复、取消和 operation
回放校验精确字段集合、数值类型/范围、玩家归属、session 列、开始请求摘要与快照指纹。终态快照保存对应 operation 编号，开始记录重放
也会验证结算/恢复/取消 operation 的请求摘要、结果和指纹。坏记录拒绝后不写资源、玩家数值、会话状态或 operation；修复后原请求可成功，
重启重放不重复结算。

文件所有权：主线独占 `nonebot_plugin_xiuxian_3/xiuxian/progression/cultivation_repository.py`、
领域合同与状态/实施文档；`/root/travel_adapter_tests` 独占 `test/test_progression_content.py` 新增用例；
`/root/slice_review`、`/root/cultivation_integrity_review` 与 `/root/demon_test_fix` 分别只读检查快照边界测试、事务/账本互证
和版本标识残留。主线统一合并并运行修炼专项、角色状态、双适配器、正式 PvE/PvP 与只读观战关联测试、`compileall`、内容 JSON
严格解析和 `git diff --check`。不引入运行时版本标识、旧格式兼容分支或玩家可见开发文案。

最终验收：`test/test_progression_content.py` 与 `test/test_progression.py` 共 46 项通过；正式战斗、竞技、队伍 PvE、切磋/训练
傀儡只读观战聚焦组 26 项通过；文档 2 项、无版本标识回归 3 项通过。`compileall` 与 48 份内容 JSON 解析通过，
`git diff --check` 通过。未运行整仓全量测试或新角色飞升长链，不将局部结果记作全量通过。

## 已闭合切片：虚空塔领奖快照严格解析与资产安全

开工证据：QQ 官方与 OneBot V11 的真实 `挑战虚空塔` / `领取虚空塔奖励` 路径均已复现：将
`void_spire_runs.reward_json` 中的 `spirit_stones` 重复键改成更大的数值后，领奖按后一个值发放
灵石。现有领奖事务在资产、图鉴、领奖记录和 operation 写入前没有严格 JSON 与奖励字段校验，
因此损坏持久化记录会改变实际资产。

范围只包含 `specials.void_spire` 的运行结果、奖励快照和领奖 operation：严格解码并校验重复键、
截断 JSON、对象字段、非负整数奖励以及运行记录的楼层/路线/状态一致性；无效记录在玩家资产、
图鉴、领奖记录和 operation 写入前拒绝，修复后原 operation 可重试或重放且只兑现一次。复用
`utils.json_cache.decode_json_strict`、共享玩家奖励事务和 operation 账本。不改塔层数值、自动战斗、
正式 PvE/PvP 结算、切磋/训练傀儡只读观战或其他试炼塔路径；不加入运行时版本标识、旧格式兼容分支
或玩家开发文案。

文件所有权：`candidate_rotation` 负责 `xiuxian/specials/void_spire_repository.py` 的严格解析实现
及 `test/test_void_spire.py` 的新增损坏记录/双适配器验收；`contract_gap` 只读核对解析点和合同边界；
主线负责文档、共享事务边界、最终聚焦测试、compileall、内容 JSON 严格解析和差异检查。适配器门禁
漂移、operation ID 命名空间和道途内容名称虽已复现，均作为未选候选，不在本条混改。

验收覆盖重复键、截断 JSON、负数/非整数奖励、损坏 operation 结果、资产与 operation 零写、事务
故障回滚、修复原 operation 重试、重启幂等回放及 QQ 官方/OneBot V11 两条真实入口；正式战斗结算和
只读观战回归保持通过后，虚空塔领奖切片进入冷却。

最终验收：虚空塔严格完整性专项 19 项通过；试炼塔 12 项、战斗/观战 21 项、适配器 29 项、内容与
无版本标识 12 项关联回归通过。源码和测试 `compileall`、48 份内容 JSON 严格解析及 `git diff --check`
完成。未跑整仓全量测试或新角色飞升长链，不将局部验收称为完整成长链；不清理用户数据，不为旧快照
补兼容字段。

## 已闭合切片：生产订单快照与结算 operation 严格回放

开工证据：`开始生产 疗伤丹`、`领取生产` 和 `恢复生产` 由统一 application/repository 对 QQ 官方与 OneBot V11
开放。只读复现先在临时数据库把 `production_orders.snapshot_json` 的 `outputs` 重复键改为 999，再走真实领取命令；
两个适配器都实际发出 999 份成品。截断 JSON 也会被宽松解析成空对象，令原本成功的冻结结果改按失败返料。生产合同要求结算只读
开始时快照；最近十条玩法切片没有进入 production，`0b1d92e` 对生产仓储仅删除过时导入，不构成生产业务切片。

范围只处理个人生产订单快照和 `production.start`、`production.complete`、`production.recover` operation：开始时将完整快照
冻结在 `production.start` 结果中，使用严格 JSON 和字段/订单列/结算结果一致性校验。无效快照、重复键、合法 JSON 的语义篡改、错误归属
或彼此不一致的 operation 结果在写资产、订单和 operation 前拒绝；修复持久化记录后，原 operation 可重试或重放且只兑现一次。复用
`utils.json_cache.decode_json_strict`、共享 operation 回放/记录以及玩家资产事务。不改配方、成本、时长、成功率、失败返还、正式 PvP/PvE
或切磋/训练傀儡观战边界，不加入运行时版本标识、旧格式兼容分支或玩家开发文案。

文件所有权：主线独占 `xiuxian/production/repository.py`、必要的生产绑定仓储调整及实施/状态文档；`next_candidates_non_livelihood`
独占新增 `test/test_production_integrity.py`，覆盖真实双适配器入口的损坏快照、operation 结果、零写、修复原请求与重启重放；
`slice_rotation_audit` 只读核验冷却、合同与双适配器资产复现，生活域代理只读比较冷却内候选。代理不修改主线生产代码或既有测试，
由主线统一处理反馈并复跑验收。验收还覆盖合法 JSON 的快照产量篡改、现有生产成功/失败、恢复顺序、账本写入故障重试和 operation 幂等。

主要候选比较：短途运输的持久化快照若已损坏，也可能在正常结算时影响资产，但生活域最近十条两次闭合，继续冷却；生产恢复顺序遮挡已修复，不以旧问题重开；
灵兽状态查询只影响展示；未完成来源合同的功法、其他三界副本与悬赏矩阵不创建入口；Web/跨服写操作继续锁定。

本切片已完成双适配器实现与专项验收，生产域随后重新进入轮转冷却。生产完整性专项 48 项及既有生产/契约专项 10 项通过；
正式战斗、竞技、只读观战、仓储边界、共享工具和无版本标识回归另按状态页记录。当前尚未登记下一条唯一切片；下一轮先比较全部开放玩家路径，
不按文档顺序或当前子插件连续开发。

## 1. 范围分层

### 已闭合切片：城镇委托快照严格回放与资产安全

开工证据：`交付委托 止血草供应` 是 QQ 官方、OneBot V11 和统一 application 的公开入口。只读复现发现，
将 `town_commission_claims.snapshot_json` 追加重复键 `"reward_stones"` 后，交付仍返回成功并按后一个值发放
灵石；背包扣除正确但奖励从内容快照的 118 被篡改为 1099。现有坏快照测试只覆盖截断 JSON，未覆盖重复键，
因此真实资产可以被损坏账本改变。

范围只包含城镇委托接受/交付的快照和 operation 结果严格解码、重复键拒绝、交付前零写校验、修复后原 operation
重试及双适配器回归。复用 `utils.json_cache.decode_json_strict`、共享 operation 账本约束和玩家资产/名望事务；
不改变委托成本、库存、配额、奖励数值、公共项目加成、服务订单、短途运输或正式 PvE/PvP。

验收覆盖内容改名/关闭后的历史回放、坏 JSON、重复键、字段类型错误、输入冲突、资产与 operation 零写、事务故障
回滚、修复重试和双 runtime 并发只结算一次。生活域近期已完成多条切片，本条仅以双适配器可复现的真实资产篡改
作为正确性例外；当时未发现轮次快照会改变领奖资格，活动严格 JSON 暂缓；服务订单和生产/运输候选继续暂缓。固定玩家短句留在领域代码，
不新增运行时版本标识、旧格式兼容分支或开发文案。

| 候选 | 证据与合同 | 本轮处理 |
|:--|:--|:--|
| 城镇委托快照严格 JSON | 双适配器公开交付可篡改真实灵石；委托合同、共享资产事务和恢复入口完整 | 选中，严格解码快照与 operation，零写拒绝 |
| 服务订单快照严格 JSON | 双适配器可篡改交付物数量；生活域近期连续切片 | 暂缓，保留为后续资产正确性例外 |
| 活动来源 operation 严格 JSON | 后续确认轮次快照重复键可改变完成奖励资格 | 已在后续灵泉切片闭合，不与本条混改 |
| 生产订单、短途运输、经济交易 | 存在相似普通 JSON 解析，但近期冷却或未完成双适配器资产复现 | 不重开，等待独立证据 |

协作采用两项只读审查：生产/生活代理复现委托资产篡改并核对冷却例外；开放域代理核对活动、任务、剧情及其他
开放路径是否存在更高风险。代理不修改工作树；主线独占 `livelihood/commission_repository.py`、委托专项测试及
本条文档，统一完成端到端验收。

实现记录：`_snapshot_object`、委托 operation 回放和事务内 operation 查询均改用 `decode_json_strict`；重复键、
坏 JSON、非对象结果在扣除材料、发放灵石、增加名望或写入 claim/operation 前拒绝。修复后原 operation 可重试，
不引入旧格式兼容分支或新的玩家文案。

最终验收：城镇委托专项 49 项通过，覆盖 QQ 官方/OneBot V11、内容变更后的历史回放、重复键快照与 operation、
零写拒绝、事务故障回滚、输入冲突和竞争交付；生活/灵田/公共项目关联 142 项、工具/仓储/适配器/文档/版本 90 项
通过。源码与测试 `compileall`、内容 JSON 严格校验及 `git diff --check` 已通过；整仓全量和飞升长链仍未运行。

本条已闭合，生活域继续冷却。服务订单、生产订单、短途运输与经济交易的严格 JSON 作为后续资产正确性候选；灵泉
事件严格 JSON 已在后续切片闭合。回退须配对代码、测试、文档与事前数据库备份，不清理用户数据。

### 已闭合切片：法器成长的历史回放与词条完整性

开工证据：`强化法器 木纹剑` 与 `重铸法器 木纹剑` 均是 QQ 官方、OneBot V11 和统一 application 的公开入口。
临时库真实复现表明，法器内容改名、移除旧别名或关闭后，原祭炼/重铸 operation 会在账本查询前重新解析当前
内容而失败；将实例 `affixes_json` 改为坏 JSON 后，重铸仍会把它当作空词条，继续扣除铁石和灵石并写入新词条。
这违反当前养成合同的历史结果优先、坏记录拒绝和失败不静默销毁唯一装备约束。

范围只包含 `item.tempering` 与 `item.refinement` 的 operation-first 回放、严格账本结果解码、重铸前词条
JSON 校验、事务回滚和恢复；复用 `utils.json_cache.decode_json_strict`、`utils.operations.operation_replay`、
共享资产扣除与现有装备实例。请求摘要只依赖保存的原始装备引用，不在回放前解析当前内容；新请求仍按当前
内容校验。已有穿脱、装备数值、奖池、正式 PvE/PvP、切磋/训练傀儡只读边界不重做。

验收覆盖 QQ/OneBot 两端真实祭炼与重铸、改名/关闭后的原 operation 回放、旧名称新 operation 拒绝、输入冲突、
损坏/重复键/非对象/非法词条值零写入、账簿故障回滚、修复后同 operation 重试和双 runtime 并发只结算一次。
不新增运行时版本标识、旧格式兼容分支或玩家可见开发文案；魔渊深层仍因合同不完整保持关闭。

| 候选 | 证据与合同 | 本轮处理 |
|:--|:--|:--|
| 法器成长回放与词条拒绝 | 双适配器真实入口；内容变更阻断历史 operation，坏词条仍扣费；养成合同和共享事务已具备 | 选中，窄修复两个成长 operation，不改数值和穿脱 |
| 服务订单快照严格恢复 | 双适配器可复现重复 JSON 键改变结算发放；生活域近期已有多条闭合切片 | 暂缓，登记后续正确性候选，不与本轮装备事务混改 |
| 活动来源 operation 严格恢复 | 后续确认轮次快照重复键可改变完成奖励资格 | 已在后续灵泉切片闭合，不与装备事务混改 |
| 生产订单、居所灵田、魔渊深层、功法来源 | 生产/生活已闭合或冷却；魔渊和功法来源合同不完整 | 不重开、不臆造来源 |

协作采用三项只读审查：装备代理核对成长合同与事务边界，生产代理核对生产/生活冷却及恢复候选，开放域代理
核对活动、世界、探索和成长路径。代理不修改工作树；主线独占装备 repository、专项测试和本条文档，统一复跑
所有门槛。代理结论保留为候选证据，不把审查结果当作代码验收。

实现记录：`item.tempering` 与 `item.refinement` 先用原始装备引用生成请求摘要并调用共享 operation 回放，
只有新请求才解析当前装备内容。实例词条改用严格 JSON 解码，重复键、坏 JSON、非对象、布尔值、字符串和非正整数
均在扣费前拒绝；回放结果同样严格校验。修复后同一 operation 可重试一次，内容改名/关闭不改变已保存结果，换输入
明确冲突。未改变装备成长数值、奖池、实例槽位、战斗快照或只读观战边界。

最终验收：装备专项 13 项通过，覆盖 QQ 官方/OneBot V11、内容改名/关闭、原 operation 回放、新旧请求边界、坏
词条和坏账簿零写、账簿故障回滚、修复重试与双 runtime 并发；属性/规则 106 项、正式 PvE/PvP 与竞技/观战 20 项、
适配器/仓储 9 项、图鉴及运营 35 项、文档与版本标识 5 项关联回归通过。源码与测试 `compileall`、内容 JSON 严格
校验及 `git diff --check` 已通过；未运行整仓全量或飞升长链。

本条已闭合，养成域进入冷却。服务订单快照严格 JSON 曾作为后续生活域正确性候选，已在后续记录中独立闭合；灵泉事件严格 JSON 已闭合；
生产/生活近期已闭合，魔渊深层与功法来源合同不完整，均不在本条扩展。回退须配对代码、文档与事前备份，不清理用户数据、不加旧格式
兼容分支或运行时版本标识。

### 已闭合切片：机缘所得材料首见与原子恢复

开工证据：QQ/OneBot新角色依次执行`开始修仙 青玄`、`寻仙问道`、`机缘寻宝 单抽`，默认内容下
`audit-material-11`请求扣50灵石并得到铁石2；背包与抽取账本已提交，图鉴却只有寻仙得到的止血草，
没有`codex.material.ironstone`。未注入资金、物品、内容或完成来源，仅选择可回放的随机请求。
当前图鉴合同明确“已结算获得物品”为材料首见来源；缺口是机缘事务未调用已有材料投影，不是新增奖池。

范围为现有机缘抽取共用事务中的材料首见、不可变首见展示/来源、查询、幂等、回滚与重启恢复。复用
`specials.codex_projection.record_material_discoveries`及当前共享角色状态、operation工具；不改奖池、
概率、保底、费用、道统回响准入、其他道历奖励来源或材料图鉴规则，不把图鉴领域逻辑塞入utils。
原operation重放不补写历史缺失首见，不自动清库；正式PvP/PvE与只读切磋/训练傀儡均不改。

实现记录：机缘结算在共享角色资产写入后调用`record_material_discoveries`，仍处于同一SQLite事务；
首见冻结来源operation、奖池键和材料展示名，后续所得仅更新最近发现时间。原operation仍先回放，不重抽、
不补写修复前漏记的旧图鉴；保持引用闭合的改名/关闭与重启均可查询历史展示。未登记材料、灵石、名望、丹药
和凭证不会派生材料图鉴。投影或账本故障整笔回滚，修复后原请求只完成一次。

最终验收：机缘/图鉴双适配器专项20项通过，覆盖真实铁石所得、十连重复首见、非材料奖励、公开查询、内容
改名/合法关闭、原operation重放、投影和operation故障回滚、坏账本只读拒绝、输入冲突及双runtime并发；
既有机缘/道统回响/运营回归30项，正式PvP/PvE及只读观战边界32项，文档2项，共84项本轮聚焦通过。
源码和测试compileall、48份内容JSON严格校验及diff检查通过；未运行整仓全量或飞升长链。三名代理职责、
文件边界和未选装备/魔渊/未定义来源候选已保留在本记录。

本条不改schema、奖池、概率、费用、保底、其他奖励来源或用户数据库；回退须配对代码、文档与事前备份。
装备祭炼/灵纹重铸回放与坏词条扣费问题作为下一轮候选，魔渊深层因进出、污染、战斗、心魔和奖励合同未闭合
继续锁定；朝阳吐纳篇和小型灵兽行囊没有来源/配方合同，不臆造入口。

| 候选 | 入口、合同与证据 | 本轮选择 |
|:--|:--|:--|
| 机缘材料首见 | 默认内容和真实新角色命令双适配器复现，现有图鉴投影/事务可直接复用 | 选中；已开放玩家动作漏记实际所得，不扩新来源或奖励 |
| 法器祭炼/灵纹重铸恢复 | 双适配器真实入道、局部资产夹具复现：改名/关闭内容后原请求拒绝；坏词条JSON下失败重铸仍扣费并写空词条 | 独立正确性候选；涉及成长结果和展示冻结，本轮优先默认健康内容下的首见遗漏，不混改装备 |
| 魔渊深层 | 仅locked地点和历史数值；进出/强返地点、两笔污染次序、深层魔核键、战斗范围及独立心魔合同未闭合 | 保持关闭，不能用堕落遗迹或突破心魔替代 |
| 朝阳吐纳篇/小型灵兽行囊 | 前者没有来源，后者为pending_recipe_key，均缺完整取得/生产合同 | 不臆造来源、成本和配方 |
| 社交/拍卖、跨服/Web | 前两域最近已闭合，后两者身份/写权限/审计前置未齐 | 冷却或继续锁定 |

最近十条玩法切片：`05d4efe`社交，`11e839e`经济，`628c494`社交，`5388b03`属性/战斗及开局仓储，
`de527ce`生活/utils，`0b1d92e`道历/persistence/utils（相邻八域仅删导入），`cf72c83`任务/晋升，
`4ab072f`灵兽，`da1a8df`世界，`dbcfb4a`道历/图鉴奖励及公共工具；均有QQ/OneBot验收。按实际代码路径：
utils/adventures/progression各三次，social/advancement/exploration/player/routine/world各两次，其余各一次；
最近五条重复为social。routine因此默认冷却，本轮仅因上述已复现结算遗漏例外进入；不是为内容搬迁或重复
重构行卷。其他未触及候选缺合同，装备恢复另有完整独立边界，不将多个问题一起修。

后续切片可合理使用子代理并行核验候选、适配器入口、事务恢复和文档合同；每个代理应有明确文件边界，
统一由主线复跑聚焦测试、编译和差异检查后再合并。代理只提供证据和可审阅改动，不改变切片边界，
不以未完成的长链测试或未闭合的来源合同替代真实验收。

### 已闭合切片：师徒出师资格与幂等结算

开工证据：当前HEAD由QQ/OneBot真实邀请、接受及成功疗伤丹生产后，同一徒弟仅将境界由聚气L3提升到
筑基L1或金丹L1，毕业即返回`MENTOR_GRADUATION_NOT_READY`；这是把最低境界误写为精确境界。
另经真实毕业复现：重复JSON键、错误关系号、非毕业状态、缺毕业时间及错账本归属仍被回放为毕业成功。
问题只影响资格与回复，未证明重复发奖；不得将其夸大为丢失或增发资产。

范围为公开`师徒毕业`的资格、现行出师参数、双方实得、宗门贡献及历史恢复。新增
`social.mentor_graduation`记录现有聚气L3下界、青石镇名望10、师傅贡献20及双方信誉2，不改变数值；
新毕业在当前规则下核验并于成功operation冻结本次规则、地点上限与实际结果，已提交请求先回放。
邀请和接受没有毕业参数承诺快照，本条不改变为邀请时冻结；邀请期限/人数/准入内容化、关系查询和解除
另待独立切片，不借修正毕业重做其状态机。按现行合同，“完成生产”不擅自改成“仅成功生产”。

| 候选 | 入口、复用与缺口 | 本轮选择 |
|:--|:--|:--|
| 师徒出师 | 双适配器公开关系与真实生产复现；沿用mentor_relations、统一应用及共享角色状态/operation工具 | 选中；社交前次道侣已闭合，当前为不同且可复现的毕业正确性缺口，不改道侣/宗门生命周期 |
| 经济拍卖 | 上轮148项拍卖及相邻验收已闭合 | 冷却，不重复开发 |
| 功法/灵具来源、分享、后续副本 | 仍无指定来源/配方、授权和副本合同 | 不臆造入口、概率或奖励 |
| 跨服/Web/支付 | 身份隔离、写权限和审计前置未齐 | 保持锁定 |

最近十条玩法切片：`11e839e`经济，`628c494`社交，`5388b03`属性/战斗及相关开局仓储，`de527ce`生活/utils，
`0b1d92e`道历/persistence/utils（八相邻域仅删导入），`cf72c83`道源quests/progression，`4ab072f`灵兽，
`da1a8df`世界移动，`dbcfb4a`道历/冒险/活动/utils，`70963ed`生产，均有QQ/OneBot验收。子插件计数：
utils/adventures/progression各三次，advancement/exploration/player/world/routine/production各两次，
其余各一次；最近五条重复为utils与属性提交/纯导入触及的advancement/adventures/exploration/player/
production/progression。重复子插件继续冷却；social本窗口一次，本轮仅修已复现出师缺口。

文件所有权：主线独占`social/mentor_repository.py`、`mentor_use_cases.py`、必要模型调整、旧
`test/test_mentor.py`及状态/计划/内容合同/数据盘点；`wayfaring_contract_candidate`独占
`mentor_rules.py`、必要的`social/__init__.py`导出、`data/社交/玩家互动.json`、新`test/test_mentor_rules.py`、内容总表和社交五份当前合同；
`gather_transaction_reuse`独占新`test/test_mentor_graduation.py`，负责真实生产后的双适配器毕业、境界与
内容变更；`source_contract_candidate`独占新`test/test_mentor_graduation_recovery.py`，负责坏账本/权限、
并发、名望/贡献/operation故障与原请求恢复。三路从预审即并行，文件不交叉编辑，主线统一复验。

验收要求：聚气L3及以上开放境界均可毕业，以下或非法境界/层数拒绝；入道和本人已完成生产/服务仍为
必要条件；坏内容、JSON、归属和状态整笔拒绝；地方名望封顶实得、双方信誉和师傅贡献只结算一次。
复用共享资产/数值/JSON/operation，不加版本分支，不改战斗或只读切磋/训练傀儡。聚焦测试、源码及测试
compileall、全量内容JSON严格校验与diff检查后提交推送；不运行完整成长或飞升长链。

实现记录：新出师读取现行规则与开放境界序位、合法层数，不再精确匹配聚气，也不把浮点层数截成整数。
名望上限引用地点，双方名望/信誉经`change_player_state_actual`取得实得；师承、宗门贡献及来源事件与
operation同事务提交，零贡献不写贡献事件。四个师徒动作移除私有账本实现，复用公共严格JSON与
`operation_replay`、`record_operation`，不新增通用规则表或兼容包装。

历史结果校验字段、严格整数、时区、动作状态、关系号、账本归属和双方稳定身份；毕业另校验冻结规则与
奖励边界。原请求不重读现行毕业内容、不重算奖励；终局只写锁不阻止历史回放，新请求仍拒绝，封禁角色
仍不可访问。玩家回复使用“出师”和中文师承状态，固定短句留代码，不把`active/graduated`显示给玩家。

三路交付后，规则代理只读终审发现浮点层数截断及终局写锁阻挡历史回放，主线修复并补入双适配器测试；
恢复代理补齐零奖励、名望/信誉封顶、坏账本、事务末段故障及跨runtime并发。适配器专项使用真实邀请、
接受和疗伤丹生产，境界、封顶名望及师傅建宗资金是明确夹具，不伪造已完成来源，也不声称完整成长验收。

最终验收：师徒规则128项、双适配器路径4项、恢复/并发12项及原师徒13项，共157项；公共社交、道源来源、
工具、内容、适配器、正式PvP/PvE、只读观战和工程门槛156项，共313项不重复测试通过。师徒组合首次155项
通过，新增零奖励两项因测试runtime没有独立内容包失败；改为显式bundled_content夹具后两项复验通过，
并覆盖移除现行规则后的原请求回放，不重复启动已通过的长组。最终文档复验不重复累加测试数。

```bash
/root/myenv/bin/python -m pytest -q --tb=short test/test_mentor_rules.py test/test_mentor_graduation.py test/test_mentor_graduation_recovery.py test/test_mentor.py
/root/myenv/bin/python -m pytest -q test/test_mentor_graduation_recovery.py -k zero_rewards
/root/myenv/bin/python -m pytest -q --tb=short test/test_social.py test/test_social_recovery.py test/test_partner.py test/test_dao_origin_task_content.py test/test_utils.py test/test_content.py test/test_adapter_normalization.py test/test_combat.py test/test_arena.py test/test_spar_interactions.py test/test_documentation.py test/test_repository_boundaries.py test/test_runtime_versionless.py
/root/myenv/bin/python -m pytest -q test/test_documentation.py
/root/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

48份内容JSON另经重复键与非有限数值严格校验通过；源码和测试compileall、diff检查通过。未跑整仓全量
或飞升长链，公共战斗回归不等同于完整成长验收。本条闭合后社交冷却，当前没有另开切片。

本条不改schema或用户数据库。旧开发毕业operation缺少必需规则快照会明确拒绝，不自动补字段或清库；
回退须配对代码、内容与事前数据库备份。邀请准入/期限/名额内容化、师徒查询/解除仍留作独立缺口，
不预选同域继续整理。朝阳功法/灵具来源、分享、后续副本、跨服/Web仍待合同或前置，不臆造玩法。

### 已闭合切片：限量拍卖的内容快照与结算恢复

开工证据：QQ/OneBot真实发布云铁并竞价后，物品改名/关闭、重建runtime，原发布operation均被
`MARKET_ITEM_FORBIDDEN`拦截；列表、竞价与成交则改用现行名称，关闭时显示内部物品键。退款和成交资产
仍正确，不把展示/回放缺陷夸大为已发生丢款。已有拍品snapshot从未被读取，竞价规则也未冻结。

本条覆盖发布、列表、竞价、超价退款、成交/无竞价流拍/超时退款和重启回放。现有20个在售槽、12小时、
10分钟宽限、数量1至99、最低起价1和500bp加价原值登记为`auction.weekly`内容，不新增品质、税费或玩法。
发布冻结物品键/名称与完整规则、期限；后续只读快照，当前物品或拍卖关闭仅拒绝新发布。周槽仍按同一UTC
起拍周open/settling占用计数，终态释放，不改为累计周次数。固定指令/错误短句留代码。

| 候选 | 证据、合同和复用 | 选择 |
|:--|:--|:--|
| 经济拍卖 | 双适配器改名/关闭重启复现；已有完整锁货/托管/退款合同，可复用公共JSON、operation和资产事务 | 选中；经济退出最近十条，完整闭合拍品生命周期而非只挪一次校验 |
| 师徒毕业 | 两适配器公开邀请/接受和真实疗伤丹生产后，筑基/金丹均拒绝毕业，仅聚气L3通过；现有境界内容和师徒仓储可复用 | 明确待修，但social刚完成道侣，优先轮转经济；不混改两域 |
| 未定义来源、分享、后续副本 | 朝阳功法、灵兽行囊、分享授权与未登记副本仍缺当前合同 | 不臆造来源、权限或奖励 |
| 跨服/Web/支付 | 身份隔离、写权限与支付前置未完成 | 保持关闭 |

最近十条玩法切片依次为：`628c494`社交(social)，`5388b03`属性/战斗(stats/combat/advancement/adventures/
exploration/player/progression/specials)，`de527ce`灵田(livelihood/utils)，`0b1d92e`行卷(routine/persistence/
utils，另八处仅删导入)，`cf72c83`道源(quests/progression)，`4ab072f`灵兽(companions)，`da1a8df`移动(world)，
`dbcfb4a`行卷称号(routine/adventures/events/utils)，`70963ed`生产(production)，`58b69b6`派遣(specials)，
均已验收QQ/OneBot。计入纯导入触及：utils/adventures/progression各三次，advancement/exploration/player/
world/routine/production/specials各两次，其他各一次；最近五条重复为utils/progression及advancement/
adventures/exploration/player，其中行卷的相邻域仅删导入。上述重复子插件冷却；economy最近一次
`31616c6`为库存隔离，已不在十条窗口，仍不重做已闭合库存工具。

文件所有权：主线独占`economy/auction_repository.py`、`auction_models.py`、`auction_use_cases.py`和
状态/计划/内容合同/数据盘点；`wayfaring_contract_candidate`独占`auction_rules.py`、新`经济/拍卖.json`、
内容清单、内容总表与经济域四份当前合同、新`test/test_auction_rules.py`；`gather_transaction_reuse`独占新
`test/test_auction_snapshot.py`，负责内容改值/关闭、双适配器生命周期与展示回放；`source_contract_candidate`
独占新`test/test_auction_recovery.py`，负责JSON、权限、并发、托管退款/结算故障和原请求重试。
三路在实现开始时并行；只读终审不重叠编辑。共享工具直接复用，不新增兼容wrapper。

验收：旧请求优先按原始选择器/身份/输入回放，坏内容仅阻止新建；坏快照/账本拒绝且无部分资产变化；
拍品、物品锁、竞价托管与冻结数量一致，成交一次、超价和过期退款一次；真实适配器、重启与并发验收。
不改变摆摊、求购、生产、师徒、PvP/PvE或只读观战。聚焦测试、compileall、全部JSON和diff检查后提交推送，
不重启完整飞升长测。

实现记录：新发布读取当前 `auction.weekly`，在原事务冻结拍品名称、卖方、数量、起价、UTC起拍周、
全部规则和期限；查询、竞价和交割实际消费快照。移除拍卖私有operation读写，复用公共严格JSON和
operation工具，资产仍由共享事务处理；被超价与过期退款共用领域退款函数，不另写灵石或背包SQL。
当前内容关闭或移除不影响履约，不添加新税费、品质要求、运行时版本或旧格式分支。

三路并行交付规则/内容、双适配器和恢复测试；两名代理另作独立只读终审。终审发现仅校验字段类型仍会
接受与动作矛盾的历史状态或错配拍品号/金额，主线补齐按动作和原请求核验，恢复测试逐项注入坏结果并
检查整库零写。期限改为aware datetime比较，验证等价带偏移时间在结束前、结束时、宽限前和宽限时的
行为。内容变更专项通过真实创建/寻仙命令获得临时内容定义的灵石与云铁；恢复专项使用明确的资产夹具，
不将二者表述为默认生产或完整角色成长验收。

最终统一复验：规则120项、内容/双适配器4项、恢复/并发14项，连同原拍卖、跨交易库存、求购和委托
10项，共148项通过；公共工具/内容、适配器、正式PvP/PvE、只读观战和工程门槛119项通过，合计267项
不重复测试。代理先前分组结果不再累加；终审补充的动作/原请求错配结果均已纳入最终148项。

```bash
/root/myenv/bin/python -m pytest -q --tb=short test/test_auction_rules.py test/test_auction_snapshot.py test/test_auction_recovery.py test/test_auction.py test/test_inventory_lock_isolation.py test/test_cross_realm_trade.py test/test_economy_commission.py
/root/myenv/bin/python -m pytest -q --tb=short test/test_utils.py test/test_content.py test/test_adapter_normalization.py test/test_combat.py test/test_arena.py test/test_spar_interactions.py test/test_documentation.py test/test_repository_boundaries.py test/test_runtime_versionless.py
/root/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

48份内容JSON另经严格重复键及非有限数值校验通过；源码和测试compileall、diff检查通过。未运行整仓
全量或飞升长链，正式战斗与观战边界只计本次专项回归，不声称全成长流程验证。

回滚时须成对回退代码与内容，并由开发者恢复变更前明确备份的数据库；不得自动清库或拼造旧拍品快照。
本条不改schema，但缺少必需字段的旧开发拍品或旧operation会明确拒绝。未改用户数据库，验收均用临时库。
经济本条闭合后冷却；已复现的师徒高境界毕业阻断留作下一候选，朝阳功法/灵具来源、分享授权、未定义
副本与跨服/Web前置仍待独立合同，不沿拍卖继续扩玩法。

### 已闭合切片：道侣缘契快照与重启续行

开工证据：QQ 官方与 OneBot V11 的公开邀请、接受已成功，关闭 `social.partner` 并重建 runtime 后，
原邀请/接受 operation 和已有缘契的解除申请均返回 `CONTENT_ERROR`；改动当前解除期限/重结缘冷却后，
旧缘契采用新值而非邀请快照。领域合同已规定邀请冻结本次参数；本条修复既有关系履约，不新增双修、奖励或资产共享。

候选比较如下；三名代理先并行只读核对，确认缺陷后转入独立文件编码：

| 候选玩家域 | 入口、缺口与复用 | 最近处理与选择 |
|:--|:--|:--|
| 道侣关系 | `邀请结为道侣`、接受及解除命令已双适配器复现；沿用 `PartnerApplication`、关系表、`operation_replay`/`record_operation`、严格JSON工具 | 社交运行时不在最近十条；选中，已有快照未消费且关闭后无法履约 |
| 师徒毕业 | `mentor_rules.is_graduation_ready` 仅接受聚气，筑基后反而不满足“达到聚气L3”；现有师徒仓储与名望事务可复用 | 独立候选，尚待真实入口专项复现；不把两种关系混改 |
| 拍卖恢复 | 新建拍卖先校验现行物品再回放，展示名也重读内容；可复用经济仓储与公共operation | `31616c6`已触及库存，候选待双适配器复现；本轮先解决已有缘契无法解除 |
| 功法/灵具来源与斗法分享 | 朝阳吐纳篇、小型灵兽行囊缺来源/配方；分享缺签名、期限和公开授权合同 | 不臆造来源或授权，保持未开放边界 |
| 其他副本、跨服、Web/支付 | 高阶副本缺现行规则；跨服身份、资产隔离及Web写入前置不全 | 继续锁定；属性/战斗、灵田、行卷、道源近期闭合，不重复重构 |

最近十条玩法切片（均验收QQ/OneBot，不计纯文档提交）依次为：`5388b03`属性/普通战斗
（stats/combat/advancement/adventures/exploration/player/progression/specials），`de527ce`灵田
（livelihood/utils），`0b1d92e`行卷（routine/persistence/utils，另八处仅删导入），`cf72c83`道源
（quests/progression），`4ab072f`灵兽（companions），`da1a8df`移动（world），`dbcfb4a`行卷称号
（routine/adventures/events/utils），`70963ed`生产（production），`58b69b6`派遣（specials），
`31616c6`交易库存（economy/items/persistence/utils）。计入纯导入改动时：utils四次，adventures/progression
各三次，advancement/exploration/player/world/routine/persistence/production/specials各两次，其余各一次；
最近五条重复为utils/progression及仅导入触及的advancement/adventures/exploration/player，均默认冷却。
social没有运行时改动（灵田提交仅校正宗门测试断言），本条不借此扩改宗门、师徒或战斗。

文件所有权：主线独占 `social/partner_repository.py`、必要的 `partner_use_cases.py`、状态/计划/内容合同，
负责事务和统一验收；`wayfaring_contract_candidate` 独占 `social/partner_rules.py`、新
`test/test_partner_rules.py`、社交域五份当前文档，负责共用严格参数解析与快照合同；
`source_contract_candidate` 独占新 `test/test_partner_snapshot.py`，负责QQ/OneBot公开生命周期、
改值/关闭/移除内容后的历史回放与续行；`gather_transaction_reuse` 独占新
`test/test_partner_recovery.py`，负责坏JSON/字段、权限、并发、账本故障回滚与原请求重试。
代理不改彼此文件或共享工具；完成后只读审阅，不同时编辑同一仓储。

验收边界：仅新邀请读取当前开放内容；旧缘契接受/拒绝、解除申请/确认/拒绝及查询读取邀请快照，
历史operation先回放，身份与双方同意仍校验，当前角色状态不能由旧快照绕过。拒绝坏快照而不补默认字段；
全程零资产/奖励/图鉴写入。保持既有过期投影语义，不重做生命周期；切磋/训练傀儡只读，正式PvP/PvE不改。
聚焦测试、源码及测试compileall、全部内容JSON严格校验与diff检查后提交推送，不启动飞升长链。

完成记录：新邀请与持久化快照共用九字段严格解析，关系转换/查询实际消费邀请快照，移除现行定义对
历史回放的前置阻断。沿用公共JSON与operation工具，不复制事务、不改schema或内容数值；坏账本同样
拒绝缺字段、错误类型和无时区时间。玩家提示不再硬写元婴门槛或“规则未完备”，固定短句仍留代码。

三路交付均已合并：规则72项、双适配器内容/生命周期12项、故障/权限/并发恢复10项；主线合并复验94项
通过。社交/师徒/文档/仓储/无版本标识32项，内容/工具/适配器归一化/正式战斗/只读观战111项通过，
三组共237项不重复测试。代理另行复验有重叠，不累加总数。规则代理和生命周期代理独立只读审查仓储，
未发现本条新增阻断。专项使用临时库，元婴是明确的境界夹具，所有关系均经公开命令创建；不声称完整成长链验收。

```bash
/root/myenv/bin/python -m pytest -q --tb=short test/test_partner_rules.py test/test_partner_snapshot.py test/test_partner_recovery.py
/root/myenv/bin/python -m pytest -q --tb=short test/test_partner.py test/test_social.py test/test_mentor.py test/test_documentation.py test/test_repository_boundaries.py test/test_runtime_versionless.py
/root/myenv/bin/python -m pytest -q --tb=short test/test_utils.py test/test_content.py test/test_adapter_normalization.py test/test_combat.py test/test_arena.py test/test_spar_interactions.py
/root/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

47份内容JSON已严格校验重复键和非有限数值。未运行整仓全量或飞升长链，未修改用户数据库；不增加版本
标识或兼容分支。当前境界序位记录本身的重排不在本条冻结合同中。社交本条完成后冷却；师徒毕业上界与
拍卖历史恢复保留为待真实入口专项复现的独立候选，不把初筛结论当已修复；来源不明和跨服/Web继续关闭。

### 已闭合切片：角色属性与普通战斗构筑同源

开工证据：`我的属性`/`我的状态`按养成内容中的 `stats.formula` 推演，普通PvE、竞技PvP和组队竞技却分别维护旧的 `100 + 4 * body` 气血公式；正式战斗不读取突破永久灵力，组队与三类秘境遗漏功法，探索入场后遭遇还重新读取现行功法。此为已开放玩家路径的数值与快照正确性缺口，不是重命名工具。范围包含普通面板、单人/队伍PvE、竞技PvP、只读切磋/训练傀儡及探索/秘境入场冻结。天劫/终局的显式高阶场景映射保留，不将其数万气血尺度替换为普通面板，也不借此改奖励、敌人或开放条件。

当前合同统一为：内容中的基础公式，加数据库已获得的永久增量一次，再合成同一份已穿戴装备、功法和体质。永久字段默认零，不能取max，也不能按境界补发未实际获得的奖励。纯规则 `stats.rules.build_stat_preview(row, content, *, equipment=(), constitution_effect=None, manual_effects=None)` 生成基础、完整派生、战斗映射、来源和指纹；共享仓储 `_build_player_stat_snapshot(connection, player)` 一次读取当前构筑。普通战斗只将灵力上限字段映射为战斗灵力，不另算基础公式；已有会话只消费冻结数值，不兼容缺字段快照。普通攻击、淬炼和战斗上限沿用普通PvE数值并在当前规则JSON登记，不保留竞技场并列系数。

文件所有权与并行协作：`wayfaring_contract_candidate` 独占 `stats/rules.py`、`stats/models.py`、`stats/__init__.py`、`combat/rules.py` 中旧属性合成器的迁出、`data/养成/规则.json`、属性域四份合同及新 `test/test_stat_rules.py`；`source_contract_candidate` 独占 `combat/repository.py`、`combat/party_repository.py`、`exploration/repository.py`、三类秘境 `ancient_domain/void_ruins/time_fort_repository.py` 和对应PvE/探索测试；`gather_transaction_reuse` 独占 `specials/arena_rules.py`、`team_arena_rules.py`、`arena_repository.py`、`team_arena_repository.py`、`combat/spectator_rules.py` 及竞技/观战测试；主线独占 `stats/repository.py`、`stats/use_cases.py`、玩家展示、必要共享读取函数、状态/计划/内容合同和 `test/test_stats.py`/新属性集成测试。跨所有权改动先交接，不同时编辑同一文件。三个代理从接口确定后并行编码，不将全部测试留到收尾。

候选比较：灵田、行卷、道源已闭合，继续冷却；朝阳吐纳篇与小型灵兽行囊缺来源/配方合同，斗法分享缺公开读取/授权合同，Web/跨服仍锁定；取消服务已有完整路径，不重复开发。属性缺口直接违背同一角色面板、构筑和开战快照合同，有可核对公式与入口，不以其他候选未定义为理由臆造规则。最近十条为 `de527ce` 生活/utils（social仅基线测试校正）、`0b1d92e` 道历/persistence/utils（八处仅删导入）、`cf72c83` quests/progression、`4ab072f` companions、`da1a8df` world、`dbcfb4a` routine/adventures/events/utils、`70963ed` production、`58b69b6` specials、`31616c6` economy/items/persistence/utils、`bf91ccd` production/utils，均有QQ/OneBot验收。utils五次，routine/persistence/production各两次，其余各一次；最近五条utils重复。stats/combat本身不在该窗口，specials/探索若触及时仅修已证明的属性入口缺口，不重做玩法结算。

验收要求：基础/永久值与装备耐久淬炼、功法体质各作用一次；面板与普通单人/队伍/竞技快照一致；内容改值会影响新构筑但不改历史会话；原operation回放、冲突、严格JSON、坏来源拒绝和故障回滚；QQ/OneBot真实入口；观战零持久化，正式PvP/PvE正常扣费结算。聚焦测试、compileall、全部内容JSON与diff检查后提交推送，不启动整条飞升长测。剩余未定义的道途/环境新乘区不凭空实现，不以本条声称所有特殊场景数值已统一。

主线补充文件所有权：`stats/presentation.py` 统一状态与属性的中文标签、数值格式，固定短句留代码；`advancement/constitution_effects.py` 复用严格JSON解码；天劫/终局仓储仅迁移体质工具导入，不改高阶profile。`test/test_constitution.py` 的两处灵力断言更新为现行基础公式；新属性集成测试覆盖共用读取、故障回滚和历史冻结。属性规则完成后，规则代理接手高阶专项只读回归，不重复启动长链。

合并验收发现旧普通战斗测试把资质写成稀疏字典或上千数值，违反现行六项5至15、合计60的合同。三路继续按独立测试文件并行修正，使用真实寻仙或明确合法资质、永久成长与共用装备夹具，不给运行时放宽校验：PvE代理负责探索/秘境9文件和`combat_fixtures.py`，竞技代理负责塔/事件/图鉴7文件，规则代理负责虚空/高阶任务/前线8文件；`progression_sources`只运行两个短用例，未运行新角色长链。主线额外修正`test_adapter_simulation.py`的旧灵力断言，并接回三个战斗/探索仓储补严格JSON解码与回合前完整冻结属性校验。只读终审再交PvE代理，不重叠编辑。

范围说明：竞技与观战本轮统一完整属性输入，既有基本招式回合仍只消费气血、攻击、先手和身法，不声称所有比例属性或神通已参与竞技结算。未定义的复杂战斗效果另行补合同；本轮不重做竞技规则或改变奖励。队伍PvE移除重复的减伤7000上限，使用构筑中已经冻结的内容上限，避免面板改值后回合仍按另一份常量截断。

终审复现并修复：战斗已胜后若快照损坏，原单人结算仍写入settled、图鉴与operation却不扣装备耐久；现单人与队伍在结算前严格解析快照和完整属性，队伍同时校验参与者与贡献映射，坏记录零写入，修复后沿原请求继续结算。构筑读取也拒绝把功法数量小数或字符串转换成整数，不扩改全仓资产工具。三份额外组队/界隙测试交PvE代理修合法夹具，终局证据三处夹具交规则代理；两个短终局证据测试运行，较长真实生产师徒项目链未运行。

冻结范围据代码收窄为探索及远古洞天、虚空遗迹、时序堡垒三类既有入场构筑；其他秘境仍按每场战斗开局冻结。本条不声称全部秘境实现整趟入场冻结，也不改其准入、节点或奖励。

主线合并后的最终复验：属性规则、内容、共享工具、仓储边界、无版本标识和文档185项通过；属性集成、正式单人/组队、探索冻结、天劫、界隙及多人内容55项通过。前者含92项新纯规则验收；后者含QQ/OneBot同源面板、只读整库比对、坏JSON/数值、快照并发、重启回放、故障回滚、完赛结算恢复及领域能量恢复原子性。初次适配器测试的一处旧灵力公式断言已修正，随后适配器/入门/装备/体质组52项重新通过。

三名代理各自交付分组验证：竞技与观战24项；探索/秘境相邻74项；塔/事件/图鉴50项（收窄强角色夹具后再复跑其中27项）；成长/前线33项并明确排除1条长链；天劫/终局/物品/神通39项；终局局部证据2项。组队/界隙额外16项亦通过，已纳入主线55项复验。以上分组有重叠，不累加为不重复测试总数。虚空塔派遣一处既有断言把封顶后实得4写成名义8，按已实施的实得合同校正，仅改测试不改结算。较长的新角色成长链与真实生产师徒项目链只改非法夹具，未运行，不能计入通过。

主要最终复验命令：

```bash
/root/myenv/bin/python -m pytest -q --tb=short test/test_documentation.py test/test_repository_boundaries.py test/test_runtime_versionless.py test/test_content.py test/test_utils.py test/test_stat_rules.py
/root/myenv/bin/python -m pytest -q --tb=short test/test_stat_integration.py test/test_stats.py test/test_combat.py test/test_party_combat.py test/test_combat_stat_freezing.py test/test_tribulation_combat.py test/test_party_boundary.py test/test_party_pve_content.py test/test_boundary_rift_secret_realm.py
/root/myenv/bin/python -m pytest -q --tb=short test/test_adapter_simulation.py test/test_onboarding.py test/test_adapter_normalization.py test/test_equipment.py test/test_constitution.py
/root/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

47份内容JSON另用严格解码验证重复键与非有限数值。未运行整仓全量或飞升长链，未新增版本标识/兼容分支，未清理用户数据。属性与战斗本条闭合后冷却，下一轮按当前状态横向选片，不按本计划历史行号继续。

### 已闭合切片：重租居所后的灵田收获与维护

开工证据：QQ 官方与 OneBot V11 均可经真实命令在租约第48小时播种并维护，第72小时重租并播种新地块，第74小时收获却返回 `PLOT_NOT_READY`；旧作物此时已熟且未枯，等新作物成熟后旧作物已枯。播种按居所分配地块，维护、收获和查询却只取角色最新地块，造成旧收成被遮挡。既有合同允许租约到期后的已开始事项继续结算；不新增产量、租期、成本或随机规则。

范围限定 `我的灵田`、`灵田维护`、`灵田收获` 的目标选择、快照校验和原事务恢复。收获选择仍在收获期限内且最早到期的成熟地块；维护选择尚在生长期且未完成维护、最早成熟的地块；查询先展示可收获地块，再展示生长地块，无活动地块才展示最近结果。过期或已收获地块不能遮挡可处理地块，选择范围始终限定本人。沿用现有 application、`FieldPlotRepositoryMixin`、共享 JSON 解码与角色资产/奖励事务，不复制背包、名望和玩家数值写入；operation 先回放，选中地块、产物、名望、图鉴和账本原子提交。

并行文件所有权：主线独占 `livelihood/field_repository.py`、必要的灵田应用文案以及本计划/当前状态，负责核心事务和最终验收；`source_contract_candidate` 独占新 `test/test_livelihood_field_selection.py`，编写双适配器真实重租、维护/收获顺序、期限边界与重启重放测试；`wayfaring_contract_candidate` 独占新 `test/test_livelihood_field_recovery.py`，编写并发、JSON损坏、事务故障与原请求重试测试；复用空闲代理 `gather_transaction_reuse` 独占生活域 README/model/workflow/use-cases，同步选择与恢复合同并只读审查实现。测试不依赖互相尚未完成的新夹具，代理不得改同一仓储、资产工具或彼此测试文件。三项在开工时并行，避免把测试和审阅全部留到收尾。

候选比较：属性显示/普通PvE/正式PvP确有公式分叉，且永久灵力增长被部分路径忽略，但需同时闭合构筑效果、队伍、秘境及历史开战快照，不能用改一行公式伪装统一，本轮登记为独立待办；朝阳吐纳篇、小型灵兽行囊和斗法分享扩展仍缺来源/配方/权限合同，不臆造；取消服务已有入口和验收，不重复开发。灵田丢收成已由公开命令双适配器复现，合同完整且生活子插件不在最近十条中，优先处理。

最近十条玩法切片及触及子插件：`0b1d92e` 道历（routine/persistence/utils，另八处仅删除无用导入）；`cf72c83` 道源（quests/progression）；`4ab072f` 灵兽（companions）；`da1a8df` 移动（world）；`dbcfb4a` 行卷称号（routine/adventures/events/utils）；`70963ed` 生产（production）；`58b69b6` 派遣（specials）；`31616c6` 交易（economy/items/persistence/utils）；`bf91ccd` 设施（production/utils）；`3e771a7` 装备（advancement）。均验收QQ/OneBot。utils四次，routine/persistence/production各两次，其余各一次；最近五条routine/utils重复，继续冷却。生活域仅因本条新复现缺陷重入，不重做此前内容化。

明确不改：行卷/道源、服务/委托/运输/生产、属性与战斗数值、正式PvP/PvE和只读切磋/训练傀儡。验收聚焦灵田双适配器、JSON严格解析、幂等冲突、并发、故障回滚和runtime重建，随后相关回归、源码及测试compileall、全部内容JSON和diff检查；不重复启动整条飞升长测。

实现核查补充：灵田原 `_operation` 被服务仓储的同名方法遮蔽，修改本地解码不会生效。主线直接复用 `utils.operations.operation_replay/record_operation`，删除灵田重复方法；共享回放解码改用已有 `decode_json_strict`，修复重复JSON键被覆盖的问题，并补工具测试。这是具体回放缺陷所需的共享工具改动，不全仓重写调用方。主线另独占 `livelihood/models.py` 与 `use_cases.py`：播种冻结潜在收成的物品名称，收获回复及历史回放不泄露稳定键，查询使用中文状态；固定短句不进入data，不为旧快照补字段。

并行审阅还复现了同一地块选择链的后续阻断：旧租约慢熟作物仍在生长，当前租约作物已枯，查询优先显示旧作物后，当前租约按存储状态被判为永久占用。播种现复用灵田时间窗口核验，只清理本人当前租约已枯地块，并与种子/精力、新地块、operation同事务提交；失败不单独提交腾地状态。另对坏快照补产物/名望语义校验，拒绝把修为伪装成灵田产物或名望键，不查询现行内容改写旧产量。

三名代理的交付均已合并：选择与双适配器文件14项通过，JSON/故障/并发恢复文件46项通过；主线最终合并复验两文件60项通过。生活/内容/适配器相邻回归58项、工具/仓储/无版本标识/文档84项、正式PvP/PvE与只读观战19项通过。所有测试均用临时数据库，除明确的故障与坏快照注入外，重租、播种、维护和收获由真实公开命令创建；没有伪造角色成长或来源账本。默认4小时作物链与临时改成长时长的边界链分别说明，不把测试配置当成默认玩法。

源码与测试compileall、47份内容JSON严格解析和diff检查通过；未运行整仓全量测试，未重启此前中止的飞升长链。没有改动或清理用户数据库。未发布存档若缺少本轮必需的收成名称快照将明确拒绝，须备份后由开发者选择新测试库，不自动迁移、清库或补旧格式。生活域本条闭合后冷却；下一轮独立比较属性口径缺口与其他未闭合路径，来源/配方合同不足的能力仍不开放。

共享回放调用方的相邻组另验收生活服务/委托、属性、道侣/宗门、云舟和道历。初跑80项中78项通过，宗门撤回的两适配器测试把坏JSON期待为输入冲突；审阅代理将HEAD `0b1d92e` 原始回放函数在内存替换，证实两项在基线同样失败。主线仅修正 `test/test_social.py` 断言为既有 `PERSISTENCE_ERROR`/可重试，不改社交实现或返回语义；不同输入仍是冲突。这是共享函数回归验收校正，不是社交玩法重入。

宗门两项与工具/文档组最终复验86项通过，以上聚焦组共301项分组通过。额外检查中既有应用层宽泛异常捕获等ruff告警仍保留，没有借此扩改其他用例。主要复验命令：

```bash
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_livelihood_field_selection.py test/test_livelihood_field_recovery.py
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_livelihood.py test/test_livelihood_residence_content.py test/test_content.py test/test_adapter_simulation.py
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_livelihood_service.py test/test_livelihood_commission.py test/test_stats.py test/test_partner.py test/test_social.py test/test_world_cloud_routes.py test/test_routine.py
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_combat.py test/test_arena.py test/test_spar_interactions.py
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_social.py::test_sect_application_withdraw_recovery_and_replay test/test_utils.py test/test_repository_boundaries.py test/test_runtime_versionless.py test/test_documentation.py
$HOME/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

### 已闭合切片：问道行卷满级可达与周期快照

开工证据：28日、30级、每级80点需要2400点，而每日100、自然周500的共同上限使任意开启星期最多获得2000至2200点，28至30级无法领取。本轮不是重复称号修复或单纯搬迁配置。保持28日/30级/80点/每日100与所有既有奖励不变，将默认周上限改为能完成四周2400点目标的最低值600；禁止配置形成任意起始星期不可满级的周期。来源只登记现有实际投影的八种，不把未投影的接取悬赏或近郊专用键另算一次。

当前规则先在领域合同闭合，再接入JSON：开卷冻结周期、点数门槛/配额、来源点数、两条奖励线、地方名望上限和展示名。当前内容关闭只禁止新开卷，已有周期继续按快照计分和领取；周期结束后只同步周期内真实来源并关闭，不允许新领奖，已有operation仍原样回放。周期已满级也必须遵守结束日期，不延长领奖；坏内容/快照原子拒绝，不兼容旧格式。

文件所有权：`wayfaring_contract_candidate` 编写 `routine/wayfaring.py`、新行卷JSON及清单注册、规则专项；`source_contract_candidate` 编写新 `test/test_wayfaring_content.py`，交回主线后独立补 `test/test_wayfaring_sources.py`；主线负责 `routine/repository.py`、`routine/models.py`、`routine/wayfaring_use_cases.py`、周期schema和整合验收。规则代理随后同步内容合同、领域 README/model-workflow 与总表，主线更新状态/计划/数据盘点，文件交接后再修改，不并行编辑同一文件。奖励复用 `utils.player` 的资产/名望/称号事务，不改适配器，不改变正式PvP/PvE或切磋/训练傀儡只读边界。

最终只读审阅发现普通 `json.loads` 会静默覆盖快照中的重复奖励键。主线在 `utils/json_cache.py` 复用内容加载器已有的重复键检查，提供持久化 JSON 严格解码；行卷快照和历史 operation 共同调用，并补工具/双重字段坏账本测试。没有复制资产或数值工具，也不全仓替换 JSON 调用。另八个仓储仅删除未使用的旧行卷导入：`advancement`、`adventures`、`exploration`、`player`、`production`、`progression/breakthrough`、`progression/cultivation_repository`、`world/travel_repository`；不是这些玩法的再次重构。

候选比较：功法朝阳吐纳篇无来源玩法/成本/概率合同，小型灵兽行囊无配方键/材料/门槛合同，不能臆造来源；其他高阶副本/跨服/Web仍缺合同或保持锁定；道源刚闭合，不重入。最近十条玩法提交为 `cf72c83`、`4ab072f`、`da1a8df`、`dbcfb4a`、`70963ed`、`58b69b6`、`31616c6`、`bf91ccd`、`3e771a7`、`a1e3179`，均验收QQ/OneBot。utils三次，生产/经济各两次，其余子插件各一次；最近五条无重复。道历此前称号结算仍属冷却，本次仅以满级不可达的独立正确性缺口例外进入，不扩道契/灵木/七日/机缘。

验收包含七种起始星期的满级上界、真实问安等来源、满级奖励、日周封顶、内容变化与关闭、周期结束、operation冲突/并发/重放、故障回滚、坏JSON和QQ/OneBot恢复。仅跑相关聚焦组，不重复启动整条新角色飞升长测。

默认内容的双适配器来源测试使用寻仙10点、问安20点与四次真实近郊采集结算达到日上限；悬赏接取及探索重放不额外计分，未写入伪造来源事件。28日满级链为临时内容将问安改为100点的真实命令测试，用来验证配置消费、周期封顶、30级领奖和到期，不代表默认规则28日完整游玩验收。规则专项独立验算七种开启星期的满级可达性。签名月道契过期后拒绝新付费领取，但原领奖 operation 在重启后仍可回放。

验收结果：行卷、道历、共享奖励、机缘、内容、无版本标识、仓储边界、只读观战和正式 PvP/PvE 聚焦回归172项通过；最后补齐月道契过期、重复JSON字段与默认来源后，行卷四份专项、`test_utils`、`test_content`、`test_runtime_versionless`、`test_repository_boundaries` 和文档专项共209项通过。源码与测试 `compileall`、47份JSON严格解析及 `git diff --check` 通过。周期schema直接加入必需的 `snapshot_json`，不补旧格式默认值；未清理或改写用户数据库。开发库旧行卷不能自动获得可信快照，应先备份，再由开发者明确选择新测试库，不伪造历史快照。

最终复验命令：

```bash
$HOME/myenv/bin/python -m pytest -q --tb=short test/test_wayfaring_content.py test/test_wayfaring_rules.py test/test_wayfaring.py test/test_wayfaring_sources.py test/test_utils.py test/test_content.py test/test_runtime_versionless.py test/test_repository_boundaries.py test/test_documentation.py
$HOME/myenv/bin/python -m compileall -q nonebot_plugin_xiuxian_3 test
git diff --check
```

本条闭合后道历冷却，未预选下一条。功法朝阳吐纳篇、小型灵兽行囊的来源/配方合同仍不足；不能因为其他候选未定义而再次整理行卷、道契或灵木。整条新角色飞升长链此前中止，本轮未重跑，不计为通过。

### 首版核心玩法（MVP-1 / `content-0.1`）

`new_user -> 寻仙问道 -> mortal -> 完成引导 -> seeker -> 选择六大道途/辅修 -> cultivator -> 感气基础循环`。

v0.1 只开放玄天界新手城、近郊荒野、灵泉谷、雾隐洞天一层和相关教学内容；公共境界正式开放凡人、感气、聚气、筑基，金丹以上只注册内容键。每个正式境界固定十层：L1–L3 入门、L4–L6 稳固、L7–L9 圆满、L10 混元，且只有 L10 可跨境。核心资产包括修为、灵石、体力、精力、材料、物品、资质、道途状态和任务奖励，全部经显式 Unit of Work 与 operation ledger 结算。

v0.1 同时开放不依赖境界层数的常驻经营与特色起点：凡人起可租居所、种灵田、交城镇委托、承接服务/短途运输；道历问安、灵木聚财、七日入道、悬赏榜、秘境试炼、主线道途、斗法留影、基础闭关、体质/道脉、低阶法器养成和灵兽/灵骑均有独立 v0.1 内容包。它们只按各自合同结算，不直接产出非法资源或跳过境界层数。

### 工程协议

平台事件归一化、消息投递能力、幂等、审计、备份恢复和安全边界属于当前工程协议；修仙3不承诺继承旧玩法命令、别名、结果文案、数值或数据结构。文本命令、按钮、Web 写入口必须调用同一 application 用例。领域层不得导入 NoneBot、Web 框架、SQLite、网络客户端或系统时间。

每条垂直切片由主线统一收敛；需要并行时，可分别委托规则与内容合同审计、适配器与恢复测试审计、资产与数据校验审计。子任务只提交可复核的代码或测试，不复制 application/repository 事务，不引入兼容分支；主线在合并前统一检查 JSON、幂等、重启恢复、双适配器路径、编译和差异。

### 切片选择与领域轮转

本文件后半部分的编号条目是已完成工作的审计记录，不是下一条任务队列。每次开发开始前只能登记一个
“当前唯一切片”，至少写明领域、入口、文件所有权、明确排除的已完成能力和验收范围；没有登记就不修改
玩法代码。一个领域完成切片后默认进入冷却，下一条从其他领域的明确缺口中选择。再次进入同一领域必须
在 `current-status.md` 写出新的可复现缺口，并说明为什么不能用既有 application、repository 或
`utils` 解决；禁止以重命名、顺手统一或历史条目靠后为理由重复重构。

**已闭合切片：灵兽结缘 - 内容关闭后的 operation 回放。** 入口为 `结缘灵兽 <灵兽稳定键>`。同一 operation 首次成功后，关闭 `beast.wood_rat` 并重建 runtime，原先 QQ 官方与 OneBot V11 均返回 `COMPANION_NOT_FOUND`，但数据库保留原实体和 operation。结缘仓储现先按原始稳定键和调用者身份核对历史 operation，只有新请求才解析当前内容、检查来源/容量并创建实体。QQ 官方与 OneBot V11 已验收成功结缘、内容关闭后的 runtime 重建回放、不同输入冲突、关闭内容下新 operation 拒绝、实体/operation 唯一性，以及 ledger 故障回滚后同 operation 重试。`test/test_companions.py` 6 项通过，`test/test_documentation.py` 2 项通过；未改灵具获取、喂养、进化、探索效果、运输或战斗快照。

候选比较：灵兽灵具装备回放也有内容变更缺陷，但其当前唯一灵具记录的生产来源仍为 `pending_recipe_key`，测试通过手工发放背包物品，故不作为真实玩家入口切片。社交过期状态缺陷只延迟状态投影，仍由时间门槛拒绝超时动作，且社交近期已触及；不优先于跨 runtime 的已提交结缘请求无法回放。问道行卷缺完整现行内容合同；其他三界副本、高阶资源链合同不足；Web/跨服继续锁定。经济、生产、世界移动和道历/机缘近期反复处理，继续冷却。灵兽域此前刚完成探索发现效果切片；本条是 QQ 官方与 OneBot V11 均可复现的 operation 恢复例外，不扩改灵兽其他能力。

只读协作由 `untouched_open_path_audit` 检查近期未触及的开放路径并提出灵具候选，`open_domain_test_gap_audit` 独立复现并确认结缘候选；二者均未修改工作树。没有并行编码，因为回放顺序、结缘事务和双适配器夹具属于同一仓储边界，由主线统一实现和验收。

### 此前横向复核：当时暂无可开工切片

当时没有新增唯一切片，之后发现的道源任务缺口另记在本文末尾。横向审查覆盖社交过期状态、即时切磋/训练傀儡与正式竞技/PvE、活动奖励/任务、成长路径及开放域中的功法来源；具体入口与未选原因记在 `current-status.md` 第 4.0 节。`social` 的过期异常回滚只延迟状态落库，后续申请/邀请和只读查询会清理或投影过期状态，未证明玩家操作被阻断。即时切磋与训练傀儡保持只读；正式 PvP/PvE 已按其领域合同正常结算。`item.manual.sunrise_breath` 没有玩家可达来源，但来源、概率和奖励规则尚未定义，不能为了填补目录覆盖而擅自放进悬赏或其他奖池。

只读协作职责：`open_reward_path_candidate_audit` 核对活动、奖励、剧情与任务；`player_growth_candidate_audit` 核对成长路径；`arena_path_audit` 核对只读观战和正式战斗边界；`open_domain_audit` 核对冷却外开放路径与功法来源。代理均未编辑文件；未并行编码，也未登记唯一切片。后续选片按 `development-guide.md` 第 3.3 节比较全部未闭合路径，并统计最近十条切片触及的子插件；没有合格候选时先闭合合同，不为提交频率臆造玩法。

**已闭合切片：世界移动 - 按地点开放状态拒绝锁定路线。** 公开命令 `前往 阵堂` 可让聚气 L1 角色从云城抵达内容状态为 `locked`、且要求金丹 L1 的 `xuantian.array_hall`；`前往 虚空门户` 可让化神 L1 角色从界隙进入内容状态为 `locked`、且要求额外 `quest.break_void_intro` 的 `void.portal`。QQ 官方与 OneBot V11 真适配器均复现成功建行程并先扣 3/10 体力。地点状态和权限字段已有内容合同；`WorldApplication` 已统一，缺口是 `TravelRepositoryMixin` 在新请求事务中没有核对当前地点内容。

文件所有权：主线独占 `xiuxian/world/travel_repository.py`、`test/test_world_cloud_routes.py`、世界移动/内容合同、当前状态和本计划。预览需将锁定目标标为未开放；新请求在 operation 历史重放检查之后、资源校验/扣除和 session 写入之前拒绝。QQ 官方与 OneBot V11 对阵堂和虚空门户均验收：体力/灵石/背包/位置不变，不创建 `travel_sessions` 或 operation；此前成功 operation 即使地点内容关闭也应先回放。明确不改云舟专用深渊门航线、其他路线参数、探索/奖励/战斗/图鉴及正式 PvE/PvP；切磋和训练傀儡保持只读观战。

横向比较：社交审查发现宗门申请撤回/审批、道侣接受过期时返回过期错误，但异常回滚使 `expired` 未写入；QQ/OneBot 可复现。时间比较仍拒绝超时动作，后续查询或业务请求会物化状态，主要影响状态投影，低于可扣体力越过锁定地点的公开准入缺陷，且社交处于冷却，故暂缓。其他三界副本、悬赏矩阵、魔渊深层和竞技场高阶资源链仍缺现行完整合同；Web 写操作和跨服身份/资产操作仍锁定，先不建入口。最近五条闭合切片为道历/机缘、生产、特色玩法、经济、生产，世界移动不在其中；此次虽是世界移动此前地点切片后的例外重入，但有两个 QQ/OneBot 公开路线的可复现权限缺陷。只读协作由 `candidate_world_combat` 核查世界/战斗开放路线，`candidate_economy_social` 核查社交、经济、生产和共享状态；两者均未改文件。没有并行编码，因为路由准入、operation 顺序和两适配器夹具位于同一移动 repository 流程。

实现由 `xiuxian/world/rules.py` 的 `destination_location_is_open` 与共享 `TravelRepositoryMixin` 共同完成；预览将锁定目标标为未开放，新行程在 operation 历史结果核对之后、资产扣除和 session 写入之前拒绝。QQ 官方与 OneBot V11 对阵堂和虚空门户均验收：体力/灵石/背包/位置不变，不创建 `travel_sessions` 或 operation；另验证地点关闭后 runtime 重建仍回放已成功 operation。`test/test_world.py`、`test/test_world_cloud_routes.py`、`test/test_world_intro_content.py`、`test/test_exploration_cloud_boat.py`、`test/test_void_refining.py` 共 30 项通过，文档测试 2 项通过；`compileall`、全部 JSON 解析和 `git diff --check` 通过。切片未改云舟专用深渊门航线、路线数值、探索/奖励/战斗/图鉴及正式 PvE/PvP。闭合后最近五条切片为世界移动、道历/机缘、生产、特色玩法和经济，世界移动重新冷却。

**已闭合切片：道历/机缘 - 问道行卷称号奖励结算。** `领取行卷 <等级> 付费` 在有效月道契和真实行卷来源均满足时，首次称号奖励进入 `grant_player_reward_actual`，但 `split_player_rewards` 不接受 `title.*`，因此会返回 `PERSISTENCE_ERROR` 并回滚。只读复现通过正式命令确认：签名月道契激活、四个业务日真实问安、领取第 1 级付费称号；数据库中资产、领取数组、claim 行和 operation 均未留下部分写入。它是近期冷却领域的开放结算正确性例外；共享资产工具不负责 honor title 持久化，故补了通用 `utils.player` 称号写入函数并在同事务复用，不做行卷规则搬迁。QQ 官方与 OneBot V11 聚焦组 78 项通过，含免费/付费来源、双适配器、原子故障回滚、同 operation 重试和 runtime 重建重放。

文件所有权：主线独占 `xiuxian/utils/player.py`、`xiuxian/utils/__init__.py`、`xiuxian/routine/rules.py`、`xiuxian/routine/repository.py`、`xiuxian/routine/wayfaring_use_cases.py`、已有称号发放 SQL 调用点、月道契当前奖励引用到的 `item.cosmetic.dao_name_frame` 正式物品记录、`test/test_utils.py`、`test/test_wayfaring.py` 和相关合同/状态/计划文档。该物品记录只补齐当前真实命令路径缺失的名称与内容引用，不改变奖励或道契规则。验收覆盖 QQ 官方与 OneBot V11 真实命令、真实问安来源、签名月道契、免费/付费称号归属展示、operation 重放、runtime 重建、输入冲突及 operation 写入故障回滚和原 operation 重试。称号、奖励与行卷 claim/operation 必须原子提交。

明确不触碰：行卷周期、等级、积分来源/上限及奖励表内容化；道契生命周期；已完成生产恢复与设施维护；正式 PvE/PvP 结算；切磋和训练傀儡只读观战。

横向比较：领域前线规则虽有 Python 常量，但当前事件记录和现行内容合同尚未完整定义它们，旧 v0.4 文件只是历史快照；先补合同，不以当前可见常量直接实现。其他三界副本、悬赏矩阵、魔渊深层、竞技场高阶资源链仍缺开放合同；Web/跨服写操作继续锁定。未选“完整内容化问道行卷”，因为它是领域重入且静态搬迁不能解释本次实际领奖失败。

协作：只读审阅委托 `open_path_audit` 实际复现命令链与事务回滚，`adapter_gap_audit` 检查双适配器及故障恢复验收边界；两者不修改工作树。称号写入、行卷领取和 operation 共享同一 repository 事务，无独立实现文件所有权，因此不并行编码；由主线统一实现并运行全套验收。闭合后没有预选下一条；下一轮须比较当前状态页列出的全部未闭合玩家路径和子包近期触及情况，不按文档顺序或单一缺陷类型续做。

**历史闭合切片：装备 - 穿脱装备原 operation 的内容变更重放。** 玩家入口为 `穿戴装备` / `卸下装备`；复现证据是
`_set_equipment_loadout_sync` 先用当前 `ContentBundle` 解析展示名，再查询 operation ledger。装备改名并移除旧名称后，
QQ 官方与 OneBot V11 在 runtime 重建后重放相同原始命令都会返回 `INVALID_EQUIPMENT`，而非已提交结果。
主线文件限定为 `xiuxian/advancement/repository.py`、`test/test_equipment.py`、本计划和当前状态；只按原始请求引用
建立 request hash、先查 ledger，再为新 operation 解析当前内容。验收还要求同 operation 改用新名称时冲突、旧名称的新
operation 按现行内容拒绝，且装备状态和穿脱流水不增加。明确排除装备目录/属性重构、槽位与装备规则、正式 PvE/PvP
结算，以及切磋和训练傀儡观战；不改变现有玩家文案。`test_equipment.py` 覆盖 QQ 官方与 OneBot V11、内容改名移除旧名、
runtime 重建后的历史原请求恢复、输入冲突、新旧名称的新请求边界和唯一流水；装备/文档/观战/正式战斗聚焦组 25 项通过。
`compileall`、全部内容 JSON 解析与 `git diff --check` 均通过。

装备穿脱功能刚于 2026-10-05 闭合，装备域原先漏列在冷却表中，故本条不是常规轮转，而是由两条只读审阅发现并独立复现的
正确性/恢复缺陷例外。轮转候选比较：问道行卷确有周期、等级、积分来源/上限和奖励硬编码在 `routine/wayfaring.py` 的
内容合同缺口，但属于已标冷却的道历/机缘域且目前玩家流程已闭合，本轮不以内容搬迁重入；其他三界多人副本和魔渊深层
缺少完整现行规则/奖励合同，竞技场高阶资源链没有独立来源和产出合同，Web 写操作仍锁定；玩家属性及共享读取没有新复现
缺口，且最近已有共享状态改动。装备 operation 回放是候选中唯一有双适配器复现证据的正确性问题。

只读协作：`equipment_stats_gap` 复现穿脱内容改名后的双适配器恢复失败，并核对属性入口无新增缺陷；
`routine_quest_gap` 核实问道行卷合同和测试缺口，结论是不应借此绕过道历/机缘冷却。两者均未修改工作树。
不并行编码，因为请求身份、账本和内容解析都位于同一装备仓储事务。本条闭合后装备域重新进入冷却；问道行卷仍是
待重新排序的合同缺口，不预先指定为下一切片。

**历史闭合切片：经济 - 跨界求购发布的原 operation 内容变更重放。** 玩家入口为 `发布求购`；复现证据是
`_create_purchase_order_once` 先用当前 `ContentBundle` 解析物品再查 operation ledger，物品改名后同一原始请求
无法回放，且回复名称重新读取当前内容。主线文件限定为 `xiuxian/economy/purchase_order_repository.py`、
`purchase_order_models.py`、`purchase_order_use_cases.py`、`test/test_purchase_order.py`、经济/内容合同、当前状态与本计划。
只把账本核对提前到当前内容解析之前、按原始选择器校验同一输入，并在订单快照冻结展示名；不重做求购状态机、资产事务、
手续费、拍卖、摆摊或其他经济路径，不改正式 PvE/PvP、切磋和训练傀儡观战。验收要求 QQ 官方与 OneBot V11 真实命令，
重建 runtime 后物品改名仍回放原订单与名称、资产只扣一次、不同输入冲突、新请求按新内容拒绝。

候选比较：其他三界多人副本、悬赏矩阵、魔渊深层缺少完整现行合同；竞技场高阶资源链没有稳定来源/产出/消费合同；
Web 写操作与跨服身份/资产能力仍锁定。审计未发现其他冷却域外合同完整且可复现的端到端缺口。经济仓储虽在
`bc24d50` 随物品内容化被触及，此次只因已证实的历史 operation 重放正确性缺陷例外重入；不得把它扩大为经济域整理。

最近连续收口的生活域切片（共享状态、名望投影、物品/运输/服务/委托回放、公共项目、居所与灵田）现视为
已闭合并进入冷却。下一条切片不得默认回到生活域；只有状态页新增独立缺口并完成上述登记后才可例外进入。
子代理仍只做登记范围内的只读合同、测试、适配器或资产审阅，不共享同一仓储和测试夹具的写权限。

领域冷却依据玩家动作、领域状态和事务边界，不依据 Python 子包或共用数据文件；世界移动与探索可共用地点记录，
但只修复地点开放状态并验收抵达，只计入世界移动。若同一切片改动探索会话、遭遇或奖池，则两个领域均进入冷却。

**历史闭合切片：世界移动 - 祖灵湖地点开放状态与公开移动验收。** `world.rules` 定义了从万兽山抵达
祖灵湖的化神/妖界声望门槛，但 `data/地图/地点.json` 曾标为 `locked`；旧测试直接改库设置地点，遗漏公开移动。
拥有者为世界移动领域；范围为地点 JSON、双适配器真实移动/恢复测试和状态文档。`include_locked=False` 现可读取地点；
QQ 官方与 OneBot V11 均覆盖预览、启程、runtime 重建后的原 operation 重放、抵达及结算重放，最终地点与体力只变化一次。
仅修复地点可达性，不改探索成本/奖励、生产配方、正式战斗或秘境结算；探索奖池/遭遇属于另一能力域，未在本轮修改。

已闭合切片记录（境界晋升解锁与圆满里程碑内容化）：7 条逐层解锁与 4 条圆满资格定义现由
`data/境界/晋升.json` 提供，原门槛、状态和结算流程未改变；晋升与资格快照在同一事务提交。
专项配置、变更回放、坏字段、事务回滚/原 operation 重试，以及 QQ 官方和 OneBot V11 均已验收，
切磋与训练傀儡保持只读、正式 PvE/PvP 未改写。该切片进入境界晋升域冷却。

已闭合切片记录（世界移动 - 祖灵湖开放状态与公开移动）：地点内容由 `locked` 改为 `open`，并由
`test_domain_sources.py` 覆盖 QQ 官方、OneBot V11 的预览、启程、runtime 重建、原 operation 重放、抵达与
结算重放；地点和体力只写入一次。祖灵湖探索奖励和规则未变，世界移动领域进入冷却。

已闭合切片记录（`codex.dao.service_settlement`）：完成道源任务“建设”的同赛季第 3 次核验后，
按任务内容引用收入服务见闻；任务奖励、事件、进度、见闻与 operation 同事务提交。QQ 官方与
OneBot V11 的边界、改名/关闭后的重放、故障回滚和原 operation 重试均已验收。该图鉴子域继续冷却。
更早的远古洞天公共事件、道统回响奖池和共享玩家数值投影各自已有独立闭合记录；它们不是当前待办。

**已闭合切片记录：灵兽探索发现效果进入探索奖池。** `data/灵兽/灵兽.json` 已给木鼠和铁背鼠声明
`exploration_discovery_bp`，灵兽合同规定发现率只影响含物品结果的奖池权重；目前开始探索虽冻结出战灵兽，
却只把体质 `drop_weight_bp` 交给奖池选择器，灵兽效果没有实际消费。入口为 `开始探索 万兽山狩猎`
（并覆盖同一权重合同支持的其他探索奖池），拥有者为探索/灵兽领域；文件限于灵兽效果解析、探索规则与仓储、
相关测试及 `current-status.md`、实施计划、内容合同和灵兽/探索领域说明。开始时冻结合并后的发现权重与实际奖项；
结算、重启和 operation 重放只读该快照。只测试与使用探索奖池权重，不改探索准入、遭遇战结算、资产事务或图鉴投影；
不碰已闭合的生活域、共享玩家状态、图鉴来源、道历机缘、师徒境界投影和境界晋升，也不改正式 PvE/PvP、切磋
或训练傀儡。主线独占规则、仓储与夹具。子代理只读审计了悬赏候选的合同/状态/入口与测试覆盖，未修改工作树；
审计发现通用悬赏结算已闭合，但完整境界/道途矩阵的覆盖表和奖励曲线尚未定义，且冒险/战斗领域刚完成切片，
因此不进入本轮。未委托并行编码，因为权重、快照和 operation 共用同一探索事务，没有独立写入边界。本切片已闭合并进入
灵兽/探索领域冷却。

上一轮候选比较：悬赏矩阵存在未覆盖境界/道途，但冒险/战斗刚收口道源主线和普通多人 PVE，完整矩阵的目标与奖励曲线
尚未约定；其他三界多人副本合同不完整，保持关闭；余下图鉴见闻缺稳定来源/奖励合同且图鉴冷却；Web 写操作仍受权限与审计合同锁定；
生产跨界配方虽有历史草案，但生产/玩家状态读取最近刚进入共享读取收口。灵兽探索发现效果已有稳定字段、明确权重含义、
可消费的开放路径和冻结奖项，因此上轮选择它，符合跨领域轮转。本轮却又从“已有悬赏奖池未接入”推导出重新进入冒险/战斗领域，
未遵守刚完成的冷却规则。悬赏属于冒险/战斗玩家功能域，不能通过单列子插件或发现孤立奖池来绕过冷却。

**最近闭合的唯一切片：开放体修近郊淬体试炼悬赏。** `reward_pool.bounty.body_trial` 已有内容奖励和品质池，
但 `data/任务/悬赏.json` 没有引用它的任务；同阶段的 `bounty.spell_trial` 已使用相同的木鼠胜利目标与
悬赏状态机。新增 `bounty.body_trial`，以感气 L1、体修道途为准入，接取后统计两次正式的近郊木鼠遭遇胜利，
奖励全部读取现有奖池。入口为 `悬赏榜` / `接取悬赏 淬体试炼` / `领取悬赏`；拥有者为冒险/悬赏领域，
范围限于悬赏 JSON、悬赏端到端测试、冒险 README、当前状态与本计划。复用现有 `AdventuresApplication`、
`SQLitePlayerRepository`、operation ledger 和统一奖励事务；不新增并列 application/repository，不改战斗规则、
探索成本、装备/图鉴奖励、完整悬赏矩阵或其他三界副本。正式 PvE 继续按自动遭遇结算；切磋与训练傀儡不参与
进度、不产生邀请、费用、奖励或图鉴写入。验收覆盖内容实际读取、非体修拒绝、两个适配器的真实木鼠胜利、
奖励/目标快照、接取与领奖重放、重启恢复和 JSON 引用错误。QQ 官方与 OneBot V11 双适配器的悬赏/冒险聚焦组
24 项通过，包含真实木鼠自动战、非体修拒绝、配置变化后的快照结算、重复操作和重启恢复。该记录不代表悬赏完整矩阵已闭合。

候选审计由 `candidate_rank_audit` 只读完成：三界多人副本合同未闭合、悬赏完整矩阵曲线未定、当时列出的道统服务见闻来源/奖励待核、
Web 写操作锁定；生活域有真实缺口但处于近期冷却，宗门创建参数属于开放路径内容收口且社交近期连续改动。
主线发现 `reward_pool.bounty.body_trial` 无任务引用后，仍选择新增对应任务并完成体修玩家路径。这项实现复用了现有悬赏事务，
但“奖池未接入”不足以推翻冒险/战斗领域冷却，也不足以证明它应排在其他领域缺口之前。本条代码与验收保留为已完成记录，
并将冒险、战斗和悬赏统一视为冷却领域；后续重新横向比较时必须先选择其他领域。未委托并行编码，因为内容、现有悬赏事务和
同一组端到端适配器夹具必须共同验收，没有独立写入边界。其他三界副本、悬赏矩阵与 Web 合同缺口继续保留；道统服务三条
现有见闻已由后续切片全部接通，不再作为缺口，详见当前状态页。

本轮无其他已登记切片。求购重放专项 4 项通过，经济、拍卖、贸易和生产委托相邻回归共 10 项通过；QQ 官方与
OneBot V11 均验证内容改名后的 runtime 重建回放、原始名称冻结、余额只扣一次、输入冲突及新请求按现行内容拒绝。
实现只复用既有求购 application/repository/operation ledger 和事务，不新增运行时版本标识、兼容分支或玩家可见开发文案。
下轮重新横向审计全部未闭合玩家路径，不按文档编号或单个 Python 子包顺序续做；生活、世界、冒险/悬赏、灵兽/探索、
境界晋升、图鉴、道历/机缘、社交、共享玩家状态与经济均按各自账本冷却或合同前置处理。

**已闭合切片：跨界求购原 operation 内容变更重放。** `_create_purchase_order_once` 现在先核对原始物品选择器和
operation ledger，确认是新请求后才解析当前内容；订单快照冻结创建时物品展示名，求购列表、结算与回放均使用该名称。
专项测试覆盖 QQ 官方与 OneBot V11、临时内容包物品改名、runtime 重建、同请求原单重放、不同数量冲突、旧名称新请求拒绝、
订单唯一性及托管只扣一次。只修复可复现的幂等/恢复缺陷，不调整市场规则和其他资产流转。

本轮已完成切片的范围记录：真实入口为 `晋升境界`；文件边界为
`data/内容清单.json`、`data/境界/晋升.json`、`data/境界/境界.json`、
`xiuxian/progression/rules.py`、`xiuxian/progression/milestone_rules.py`、
`xiuxian/progression/milestone_repository.py`、`xiuxian/progression/cultivation_repository.py`、
`test/test_progression_content.py`、`test/test_progression.py` 及对应数据合同/状态文档。
将现有 7 条逐层解锁和 4 条条件里程碑的稳定键、展示文字、境界/层数/数值门槛迁入严格校验的 JSON；
不得改变现有门槛、解锁状态、事务、命令或奖励，不增添新的境界功能。层级内容关闭后不再用于新晋升；
已提交的 operation 与资格记录保持原结果。幂等、内容变更回放、无效引用拒绝、事务故障回滚/重试，
以及 QQ 官方、OneBot V11 两条适配器路径均须覆盖。切磋与训练傀儡保持只读，正式 PvE/PvP 结算不改写。
主线独占规则、仓储与测试夹具，不启用子代理：本切片边界紧密共用同一晋升事务，拆分审阅没有实质并行收益。
比较过的候选包括：其他三界多人副本（合同尚未闭合，保持关闭）、余下图鉴见闻（来源/奖励合同未闭合且
图鉴冷却）和 Web 写操作（权限/审计合同锁定）。本轮选境界是因为玩家入口、业务定义和事务均已具备，
可在不改变玩法的前提下闭合 JSON 合同；按新增的候选排序规则，后续纯内容搬迁不得优先于已有合同、
但缺少玩家闭环的能力。

### 运营扩展

扩展只包含平台适配、受控 Web 运营和内容发布。修仙3明确不加入媒体、WebDAV、第三方帐号、番剧、小游戏或娱乐积分；它们不是后置玩法，也不保留内容占位。

## 2. P0-P8 依赖图

```text
P0 产品与内容基线冻结
  -> P1 可运行内核与确定性端口
  -> P2 持久化 / 事务 / 适配器安全基础
  -> P3 新用户、寻仙问道、凡人、引导、道途入道
  -> P4 感气十层、状态卡、资源/背包、常驻经营与道历运营
  -> P5 玄天界探索、生产、悬赏/秘境/主线、闭关与基础构筑（探索遭遇已接自动回合）
  -> P6 宗门、队伍、委托、固定市场、世界事件、机缘寻宝/行卷与经济恢复（战斗前置）
  -> 自动回合 PVE 扩展切片：训练/具名遭遇/天劫（天劫三阶段验收已完成）
  -> 双人 PVE / 终局战 / PvP（必须分别通过前置门槛）
  -> P7 魔界/妖界入口、阵营、Web 运营与隔离扩展
  -> P8 金丹以上、三界正式内容、发布周期、赛季与兼容清理
```

P7 的 Web 运营部分可并行于 P6 的稳定化；P8 只能建立在每个既有切片完成恢复演练、内容版本冻结和观测指标之后。P0-P8 是工程风险和能力阶段，不与 `content-0.1` 到 `content-0.6` 一一对应；同一个内容版本可以跨多个 P 阶段，单个 P 阶段也可以提前实现未来版本的锁定规则。

角色资产与数值属于共享基础设施：背包、灵石和角色资源必须通过统一的状态变更内核完成
校验和持久化，资料卡、状态查看与战斗快照必须复用同一归一化读取入口。领域代码只传入
奖励、消耗或带上限的数值差异，不得重新实现资产序列化、余额校验或字段转换。

## 3. 分阶段交付、验收与回滚

| 阶段 | 交付物 | 主要风险和控制 | 最低验收 | 回滚点 |
|:--|:--|:--|:--|:--|
| P0 | 设计总纲、完整内容开发总表、域索引、v0.1-v0.6 发布快照、稳定键、数值和参考边界 | 旧玩法/数值回流；文档交叉链接与稳定键检查 | JSON 格式校验、`pytest -q`、`git diff --check` | 仅撤回未发布的文档变更；不改运行数据 |
| P1 | 包配置、类型化配置、路径边界、Clock/Random/ID、组合根、manifest、健康检查 | import 副作用、路径越界、非确定性测试 | `pytest -q`、编译、两次本地启动不重复注册 | 停止运行时，移除 P1 包；无用户数据迁移 |
| P2 | SQLite 迁移/UoW、operation ledger、备份恢复、DTO、适配器契约、限流去重、Web 安全契约 | 重复结算、半迁移、路径/会话绕过 | 空库/重复迁移/异常回滚、operation 重放、备份恢复、OneBot/QQ fixture | 关闭写入口，恢复快照；保留 ledger 供审计 |
| P3 | `player.create`、寻仙问道、资质快照、凡人引导、道途/辅修选择、资料卡 | 初始奖励双发、随机重掷、阶段跳跃 | 玩家状态机、60 点资质、重复 operation、文本/按钮同用例、数据库失败回滚 | 关闭角色写 feature，恢复 P3 前备份；不删 operation |
| P4 | 感气 L1–L10、状态卡、体力/精力、背包、基础物品和 v0.1 常驻经营（居所/灵田/城镇委托/服务/短运） | 自动循环刷资源、层数跳跃、经营变相产修为、容量/消耗不一致 | L1–L10 阈值/晋层/混元突破门槛、经营无修为写入、库存/订单/维护幂等、资源不足、跨适配器冒烟 | 关闭对应 action，回放/补偿失败 operation，恢复快照 |
| P5 | 玄天界移动、短历练、雾隐洞天、基础生产、筑基准备；战斗规则、内容键、探索遭遇自动回合、快照和回放 | 会话并发、配方通胀、战斗失败奖励误发 | 地点条件、会话状态机、探索战斗快照/回放校验、生产失败、探索过期；不得由客户端提交行动 | 停止新会话，结算/取消已有会话，恢复世界快照；保留已创建战斗回放 |
| P6 | 宗门、师徒、队伍/匹配、委托、固定摊位、任务、灵泉事件；补齐 PvP 前置 | 跨玩家锁定、市场悬挂、奖励重复、匹配越权 | 锁定/成交/过期恢复、队伍确认/解散、贡献和领奖幂等、事件轮次回放；战斗仍不启动 | 冻结交易、匹配与领奖，执行补偿/回收，恢复市场与事件快照 |
| P7 | 魔界/妖界入口、污染/血脉、阵营声望和 Web 运营 | Web 越权、阵营状态不可解释 | 权限/CSRF/路径、污染/血脉状态流水 | 按 feature 关闭运营入口；核心三界资产不回滚 |
| P8 | 金丹至飞升内容、多人副本、赛季、三界战争、发布观测 | 高阶数值膨胀、赛季迁移、长期兼容债务 | 完整赛季演练、恢复演练、内容包回滚、稳定键迁移 | 停止新赛季，恢复赛季快照并保留历史结算 |

特色系统的独立切片顺序：

1. `routine`：道历问安/补录、灵木聚财、七日入道、道号/功业、机缘密令、机缘寻宝。
2. `adventures`：悬赏榜、秘境试炼、主线道途、斗法留影查询/分享。
3. `advancement`：闭关修行、体质根性、道脉天书、神通参悟、法器祭炼/灵纹重铸。
4. `companions`：灵兽/灵骑实体、升级、蜕变、灵具/鞍具、休养与快照战斗。
5. 后置运营：日/周/月道契、机缘寻宝、问道行卷的正式支付凭证接入；核心先以测试凭证完成，不把外部支付失败耦合到游戏事务。

## 4. P3 垂直切片顺序

P3 不按“先建全角色表、再写全部玩法”推进，按以下可回滚切片逐条完成：

1. `player.create` + 只读资料：无资产奖励，验证身份和 operation 规则。
2. `player.start_seeking`：资质快照、初始资源、任务可领取标记和随机重放。
3. 三项凡人引导：教学阅读、教学采集、教学服务，建立体力/精力/地点规则。
4. `player.enter_cultivation`：六大道途与 `support` 的三类主辅修选择、入道奖励、感气 L1 入口。
5. 资料卡与帮助：读取同一 query DTO，展示 `realm_key + realm_layer + realm_segment`；文本/Markdown/键盘只做呈现降级。

每条切片必须同时提交：领域不变量、application DTO/用例、迁移、operation 幂等、命令/按钮适配器、领域/集成/契约测试、内容引用、观测字段和回滚步骤。任何资产变化不得绕过 UoW/ledger。

### 战斗扩展门槛

训练傀儡、具名高阶遭遇、探索遭遇、双人 PVE 和天劫试炼已经通过最小自动回合切片接入。新增终局多人 PVE、
终局战或 PvP 前，仍必须完成对应的角色状态机、属性/资源、装备/物品、技能/道途、队伍/匹配、
Unit of Work、operation ledger、回放恢复和 QQ/OneBot 消息降级验收。所有新类型继续按自动
回合合同实现：服务端选择行动，客户端不得提交攻击、防御、技能、目标、伤害或结算结果；
PvP 使用所有参与者开始快照、断线继续、匹配保护、回放和无永久资产损失规则。

## 4.1 功能切片验收模板

实施任意境界或玩法时，提交记录必须按以下顺序填写：入口与权限、领域实体/状态机、
前置/成本/产出/失败、application DTO 与 operation、迁移和唯一约束、内容键引用、
QQ/OneBot/Web 适配器、公式/并发/回放/故障测试、观测字段、关闭新建和历史会话处理、
备份恢复与回滚命令。模板与完整功能矩阵见 [完整内容开发总表](content-development.md)。

## 5. 数值与内容变更规则

- MVP-1 的 `player-onboarding-v0.1.0`、`qualification.v0.1`、`gather.v0.1`、`progression-0.1.1` 和对应内容键是固定基线；全部版本的十层阈值和开放边界以 `content-development.md` 与 `foundation/progression/layers.md` 为准。
- 使用整数与万分比；`10000 = 100%`。不在领域层使用浮点或系统时间。
- 改动奖励、突破门槛、概率、配方、敌人或地点时，直接更新现行 JSON 与消费代码，并提供公式测试、经济影响说明与回滚说明；不新增版本字段。
- 已结算 operation 永远读取历史业务快照，不因内容文件更新被重新计算。

## 6. 当前状态与下一步

心魔独立事件切片已完成：`event.heart_demon_trial` 使用独立事件投影记录突破失败来源 operation、业务快照和截止时间；`心魔事件` 查询会自动结算逾期 `heart_demon.face`，重复选择返回 `HEART_DEMON_ALREADY_RESOLVED`。三界贸易、限量拍卖、跨界求购和界隙多人副本均已完成。

当前已开放、合同/锁定范围和命令边界统一维护在[当前开发状态](current-status.md)。本计划只维护
依赖顺序和验收门槛，避免在这里复制第二份功能清单。

以下为已完成垂直切片的审计记录，不是开发顺序或下一任务队列；工程依赖阶段见上方 P0-P8。

0. **已完成**：道侣关系生命周期。双方按内容 JSON 的境界门槛结缘，邀请、接受/拒绝、查询、解除双方确认/拒绝、过期恢复和同对冷却均使用独立关系表、事务锁和 operation 账本；QQ 官方与 OneBot V11 共用 application，关系流程不改动任何玩家资产。

0.1. **已完成**：灵根体质效果。`constitution.spirit_root` 已从当前内容包开放，选择/重塑仍沿用体质事务与 operation 账本；灵力上限效果在训练观战、单人/组队 PVE、正式 PvP、渡劫和终局战的统一战斗快照中按冻结内容生效。QQ 官方与 OneBot V11 已覆盖选择、重放、内容改值、观战只读和资产隔离。

1. 探索遭遇和双人 PVE 已完成；终局最终战多人会话（1 名发起者、最多 4 名协助者）已接入队伍快照、资产锁、协助者结算权限和唯一奖励结算。
2. 终局最终战玩家入口和赛季候选/飞升、留界、协作三榜匿名结算已完成；终局地点移动、凭证生命周期和个人结局由独立状态机驱动；正式大师作品、公共项目、师徒毕业和个人挑战证据生产者已通过 QQ/OneBot 命令链验收。完整新角色命令链现已从新手推进至飞升结局；高阶来源审计、失败恢复和剩余内容按[当前开发状态](current-status.md)执行。
3. **已完成**：正式异步 `1v1` PvP `arena.spar` 垂直切片；玩家防守快照、匹配/挑战授权、资产隔离、15 回合服务端行动、反刷、回放恢复和 QQ/OneBot 验收均已接入。
4. **已完成**：`arena.rank`/`arena.practice` 模式配额、同段/授权匹配、零资产练习、反刷、回放恢复和 QQ/OneBot 验收。
5. **已完成**：2v2/3v3/2v3 `arena.team`；复用已确认双人或三人竞技队伍，保存队伍快照、同段匹配、资产隔离、服务端行动、独立回放和 QQ/OneBot 验收。
6. **已完成**：竞技场图鉴/地区名望正式投影；个人和组队对局在同一事务内写入不可变图鉴首见、参与/胜负活动记录、地方名望和投影 ledger，重复 operation 不重复投影。
7. **已完成**：跨服匹配前置数据层；平台身份路由、只读赛季冻结快照和结算审计已接入，仍不开放跨服匹配或身份合并。
8. **已完成**：跨服恢复演练与观测审计；竞技场备份工件受数据根路径约束，恢复前创建独立快照，恢复后执行 SQLite 完整性、外键、投影/身份/赛季/审计引用校验；历史 operation 可重放且不重复投影，失败保留原库并记录 request/operation、版本、结果、失败原因和耗时。
9. **已完成（v0.2 世界垂直切片）**：云城普通移动、云舟洞天二层/魔界引导航线、费用与凭证快照、`running/arrived` 恢复、operation 幂等，以及魔界风险确认和阵堂生产权限拒绝均已接入并通过 QQ/OneBot 模拟适配器测试；云铁采集的精力/许可门槛、矿兽自动战、洞天二层地点门槛和精英自动战也已接入并通过双适配器测试。
10. **已完成（v0.2 世界垂直切片）**：云铁矿区悬赏、云舟试炼（含风暴选择、QQ/OneBot 模拟适配器验收）、洞天精英悬赏凭证来源和五条个人生产配方（材料/精力/灵石扣除、工具耐久、质量快照、失败返还、权限复核、QQ/OneBot 验收）玩家路径已接入。
11. **已完成（v0.2 世界垂直切片）**：洞天二层设施槽位锁定/维护和成品使用效果已接入；个人/宗门所有者、业务日维护幂等、欠费停用、订单占槽/释放、成品效果和 QQ/OneBot 验收均已通过。魔界核心区仍关闭，不得作为 PvP 夹具入口，也不开放跨服匹配或身份合并。
12. **已完成（v0.3 三界单人与核心入口切片）**：魔界堕落遗迹和妖界万兽山单人探索均已接入元婴 L1/每日次数/地点声望/跨界惩罚/版本快照；魔界额外池提供魔核、魔界声望或 `item.clue.demon_contract`，失败进入神魂疲劳；万兽山额外池提供妖血、妖界声望或 `item.clue.beast_bloodline`，祖灵事件分支暂不发资产，失败不改变血脉稳定。探索与自动战斗均冻结 `content-0.3` 及对应规则版本；两个线索均为绑定展示物，首条 `recipe.contract.beast_pact` 已通过妖修道途、元婴、跨界地点、妖血/灵石/精力快照和独立 `production_item_bindings` 接入正式生产，契约成品绑定 24 小时并受单槽位限制；心魔分支已完成独立事件切片；`quest.demon_main_1` 通过已结算探索会话核验两次胜利和魔界声望 200，原子写入 `quest_events`、`quest_progress`、`intro_json` 与 operation；魔渊集市移动已接入元婴 L1、魔界声望 `>=200`、5 分钟/12 体力/500 灵石，万兽山移动已接入元婴 L1、妖界声望 `>=200`、5 分钟/12 体力，两个入口事务均原子校验声望并冻结准入快照，QQ 官方与 OneBot V11 已验收；固定 `trade.xuantian_to_demon` 和 `trade.xuantian_to_beast`、三界贸易、限量拍卖、跨界求购均已开放并通过双适配器幂等测试。`event.demon_invasion` 已接入每周三 20:00 UTC 的 3 小时轮次、运输/个人设施维护/战斗来源投影、个人贡献 50 门槛和双适配器领奖，个人设施可由玩家按服务端业务日维护，`xuantian.war_front` 可在活动窗口内移动并开始固定自动战。`cave.boundary_realm` 界隙多人副本也已完成：2–5 人/5 分钟确认窗口、元婴与三界主线证据、30 体力/队长 1 枚神魂晶的原子扣除、跨界快照、服务端自动回合、失败神魂疲劳、独立奖励和恢复锁。魔界完整核心区、化形圣地、完整技能系统和跨服匹配仍未开放。
13. **已完成（v0.3 战斗扩展）**：`skill_masteries` 的技能等级/有效效果在单人和界隙战斗开始时冻结，服务端按道途选择主动技能并把技能键写入行动回放；界隙队伍增加 `downed`、每名成员一次复起、25 点神魂原子扣除、5/10 回合两人防御检查、全队神魂冲击、贡献累计、固定奖励排序和 roll。QQ 官方与 OneBot V11 混合队伍已覆盖技能、复起、失败疲劳、唯一奖励和重放。

14. **已完成（v0.3 公共事件与阵营轮次基础）**：界隙、魔渊、万兽三类已开放多人副本及公共事件/阵营轮次使用独立会话、来源 operation 投影、恢复和双适配器验收；尚未登记的其他三界多人副本仍关闭，继续保持跨服匹配、玩家间资产转移和复杂市场关闭。

15. **已完成（v0.3 跨界多人副本扩展）**：新增 `party.demon_realm` 与 `party.beast_realm`，分别开放堕落遗迹魔渊领主和万兽山始祖副本；开始事务校验地点/元婴/遗迹权限或妖界声望/污染/体力，冻结污染、血脉和技能快照，原子扣除每名成员 20 体力。副本行动记录污染冲击、祖灵召唤与清除，结算写入跨界材料、阵营声望、世界功勋、贡献排序、唯一奖励、失败神魂疲劳和回放；旧队伍表迁移、QQ 官方与 OneBot V11 混合适配器路径均已测试。

16. **已完成（v0.3 公共事件与阵营轮次）**：新增 `event.beast_trade` 七日轮次和 `event.boundary_rift` 两小时轮次，复用 `world_event_rounds`/来源 operation 投影；妖界贸易支持已结算固定贸易与妖血提交，界隙裂痕支持角色参与的已结算界隙队伍胜利，全部按轮次/角色/来源去重。查询、贡献和领奖会恢复过期轮次，奖励按独立 operation 唯一；`event.demon_invasion` 与新事件统一覆盖来源核验、完整轮次结算和 QQ 官方/OneBot V11 领奖测试。
17. **已完成（v0.3 三界赛季最小闭环）**：新增独立三界赛季规则、模型和 repository，按 28 日 UTC 窗口冻结阵营功勋/多人副本贡献/宗门贡献三榜；公开榜单匿名化，前 100 名可在 7 日窗口内领取绑定神魂晶与世界功勋，多榜奖励叠加。查询、冻结、领奖和历史恢复均幂等，并通过 QQ 官方与 OneBot V11 模拟适配器测试。
18. **已完成（v0.3 宗门战最小闭环）**：新增独立宗门战规则、模型、repository mixin 和 application；每周两轮/30 分钟、等级与报名费门槛、最多 10 人快照、占点/击败/运输/维修来源 operation、轮次自动结算、胜方宗门功勋、个人世界功勋、24 小时自动发放和幂等恢复均已接入。QQ 官方与 OneBot V11 模拟适配器测试覆盖权限、费用、来源归属、次数限制、结算、领奖和隐私字段。
19. **已完成（v0.3 普通多人 PVE）**：新增 `standard_pve` 队伍类型和 4–5 人规则，复用近郊/雾隐洞天普通敌人与独立 `party_battle_sessions`；命令、类型约束、全员确认、5 人上限、全员开始快照、自动回合、唯一奖励、启动/结算幂等和旧 `parties` 表迁移均已接入。QQ 官方与 OneBot V11 混合适配器专测及全量回归通过。
20. **已完成（v0.3 三界竞技场扩展）**：新增 `arena.three_realms` 本地个人匹配；元婴 L1 与三界竞技许可门槛、阵营/盟约/污染/血脉/许可冻结、同阵营与跨阵营战术环境、15 回合服务端自动战、回放、反刷、投影和 operation 幂等均已接入。竞技场表约束与旧库迁移已更新，QQ 官方与 OneBot V11 覆盖发布、延迟、列表、挑战、拒绝门槛、同/跨阵营回放和资产隔离。
21. **已完成（v0.5 前置数据与赛季投影）**：跨服宗门战先接入本地最多 15 人 roster 冻结、shard 标识、远端结算导入审计、幂等和冲突保护；不开放跨服匹配、堡垒准入、身份合并或奖励/资产转移。三界赛季新增 `three_realms_season_score_events`，查询/冻结前实时投影事件、多人副本和宗门来源 operation，按赛季/榜单/角色/来源唯一，冻结后读取不可变排名。QQ 官方与 OneBot V11 相关路径均已覆盖。
22. **已完成（v0.5 跨服宗门战本地周赛）**：虚空堡垒等级/锚/公共钱包准入、48 小时建造和每周维护、30 宗门报名/15 人 roster 冻结、`enemy.sect_war_engine` 服务端自动回合、60%/30% 阶段的 `repair`/`break` 首次选择锁定、占点/击败/摧毁机关来源 operation 反刷、前 3 宗门公共奖励箱、宗主/副宗主审计化分配、7 日未分配物品保留和 `season.void_frontier.<week_id>` 周奖励均已接入。迁移、application DTO、QQ/OneBot 端到端、并发、恢复、过期和幂等测试已通过；跨服匹配、身份合并和玩家间资产转移仍关闭。
23. **已完成（v0.5 联盟合同与虚空信标）**：新增独立信标规则/DTO/repository/application 及专用表，active 堡垒下 10 锚/30 阵砂、24 小时建造、每周 2 锚维护和 `void.sect_fortress` 航道最低 1 锚折扣；新增生产联盟合同与研究同步表，双方宗主确认、24 小时窗口、7 天有效期、提前解除双确认、一次 10000 公共钱包违约费、双方冷却和每周 3 项 `recipe_key` 解锁标记同步，明确不共享任何玩家/仓库资产。QQ 官方与 OneBot V11 端到端、过期、权限、幂等、资产隔离和全量回归已通过；跨服匹配、身份合并、玩家间资产转移和复杂市场仍关闭。
24. **已完成（v0.5 跨服社交恢复演练）**：新增独立 `social` 恢复规则、DTO、repository、用例和迁移，备份工件固定在 `data_dir/backups/social` 并校验路径、哈希、schema、SQLite integrity/foreign key；恢复前创建独立快照，恢复前后校验宗门战/联邦结果、虚空堡垒与信标、联盟研究、身份路由和竞技审计引用。恢复失败保留原库并记录失败原因，已结算跨服 operation 可重放且不重复结算；QQ 官方与 OneBot V11 管理入口覆盖权限、备份、校验、恢复和幂等，跨服匹配、身份合并和玩家间资产转移仍关闭。
25. **已完成（v0.4 领域前线活动）**：新增独立 `domain_front` 规则、模型、repository、用例和迁移；UTC 4 小时活动窗口切分 30 分钟轮次，加入事务冻结化神/领域/宗门/裂痕资格和 20 人宗门名额，服务端自动领域战与占点来源按角色/轮次/operation 唯一投影，个人贡献 100 门槛、轮次恢复领奖和 `season.domain_war` 21 日匿名赛季冻结/领奖均已接入。赛季冻结前实时投影领域前线贡献、宗门建设 `quantity * 2` 和化神配方成品每件 `+5`，并开放 `兑换领域核心 <赛季编号>`（20 碎片换 1 核心、每角色每赛季一次）。QQ 官方与 OneBot V11 覆盖成功、门槛、幂等、恢复和资产回滚；完整虚空档案副本、其他复杂多人副本及跨服匹配仍关闭。
26. **已完成（v0.5 虚空档案阶段 A）**：新增独立 `void_archive` 规则、模型、repository、用例和迁移；`void.archive_ruins` 已结算航道绑定 `enemy.archive_keeper` 服务端自动战，同一航道唯一结算，档案产出每周 1 份，超限转虚空晶；新增 `recipe.void.crystal_refine`，并以航道结算、守卫胜利、生产完成订单投影 alpha/beta/gamma 周任务。三项任务按 UTC 周唯一领奖，完成后激活 7 日 `event.archive_unlock`；QQ 官方与 OneBot V11 共享 application 和 operation ledger 已覆盖。阶段 A 的玩家入口、周任务和恢复已完成；跨服匹配、身份合并、玩家资产转移仍关闭。
27. **已完成（v0.5 虚空前线阶段 B）**：新增独立 `void_frontier` 规则、模型、repository、用例和迁移；28 日赛季实时投影航道完成/风暴救援/跨服胜利/自然结束联盟合同分数，赛季结束后冻结匿名玩家与宗门榜，前 3 宗门写入 7 日虚空集市优先权；每周最多 5 个待领取箱发放虚空功勋与联盟积分，季末 7 日后未领取箱转换为绑定功勋，前 100 名可幂等领奖。QQ 官方与 OneBot V11 已通过跨适配器测试；跨服匹配、身份合并、玩家资产转移和复杂市场仍关闭。
28. **已完成（v0.6 终局移动状态闭合）**：虚空航道结算在同一事务更新玩家抵达地点并冻结到 operation 结果；QQ 官方与 OneBot V11 真实命令链已覆盖 `void.portal -> void.first_route -> void.archive_ruins -> dao.origin_gate`，道源门不再需要手工修改 `location_key`。
29. **已完成（v0.6 道源证据生产者验收）**：QQ 官方与 OneBot V11 在独立数据库中，使用正式命令完成三界回响主线、个人合道挑战、炼虚 L10 大师作品生产/交付、三周公共项目贡献/结算、三次师徒生产/毕业，并以这些已结算 operation 驱动合道许可和守界/建设/传承任务。该验收从高阶境界/资源起点开始；之后的新角色完整链由第 53 条验收。
30. **已完成（v0.6 炼虚许可真实入口）**：化神受控起点通过 QQ 官方与 OneBot V11 正式命令完成三次界壁试炼、档案航道进入/结算、档案守卫自动战、档案交付和炼虚许可领取；档案航道在三次试炼前拒绝且不扣资源，探索不再回退到旧版直接发放档案物品的入口。新角色专项已进一步覆盖神魂淬炼、公开市场资源来源和炼虚突破，抵达炼虚 L1；后续完整链由第 53 条验收。
31. **已完成（v0.6 天劫试炼资产与重试验收）**：QQ 官方与 OneBot V11 正式命令链完成身心劫、三界劫、道果劫三阶段，token 按每次试炼独立扣除，成功/失败结果、进度、债务、道果奖励和回放均按角色/会话隔离；失败试炼只进入自身冷却，冷却后重试不重复推进成功次数，重复开始/结算 operation 可恢复。后续新角色完整链由第 53 条验收。
32. **已完成（v0.6 终局生产到结局命令链）**：QQ 官方与 OneBot V11 在同一运行时中，以正式命令完成飞升凭证终局配方（含未完成拒绝与 operation 重放）、道源门→天劫台移动、五人终局战发起/自动回合/结算和飞升结局选择；不直接写入终局状态。该切片的上游完整玩家链之后由第 53 条验收。
33. **已完成（v0.4 化神材料来源切片）**：祖灵湖地点移动与 `explore.ancestral_lake` 已接入化神、妖界声望 3000、血脉稳定 50、每日 2 次和服务端祖灵湖自动战；结算冻结血脉前后值并产出祖灵血/妖界声望。灵泉采集新增灵泉水来源；`recipe.fruit.soul_seed` 已注册为祖灵湖配方，按七日滚动冷却生产 `item.soul_seed`。化神许可领取事务一次性发放绑定魂种，全部通过 QQ 官方与 OneBot V11 双适配器测试；后续新角色完整链由第 53 条验收。
34. **已完成（v0.1 上游材料补齐）**：按内容合同注册 `recipe.pill.focus_low` 与 `recipe.pill.foundation_draft`；感气炼丹辅修角色可制作焦点丹，聚气炼丹辅修角色可用灵叶 3、阵砂 2、铁石 2、基础丹炉和 8 精力制作绑定筑基丹。订单日限、失败返还、工具耐久、不可交易边界、operation 重放和 QQ/OneBot 命令路径已验收。
35. **已完成（v0.1 突破保护来源）**：按 `production-0.1.1` 注册 `recipe.pill.qi_guard` 与 `recipe.pill.foundation_guard`；感气/聚气炼丹辅修角色可分别制作聚气护脉丹、筑基护脉丹，绑定成品只能在对应突破失败时消耗，成功不消耗。两条配方的材料、精力、工具耐久、日限、失败返还、不可交易边界和 QQ/OneBot 命令路径已验收。
36. **已完成（v0.2 宗门仓库兑换）**：固定兑换、每日 5 次限额、每日建设、原料/灵石捐献、宗主/副宗主补给已接入；贡献和库存由玩家命令链取得，绑定物拒绝捐入，容量和权限受事务校验，库存/贡献原子扣减并支持 operation 重放、审计及并发控制。QQ/OneBot 模拟事件均已走通捐献→补给→兑换；后续新角色完整链由第 53 条验收。
37. **已完成（v0.2→v0.4 晋升上游）**：修复凝核丹只能由金丹角色生产却是金丹突破必需材料的循环依赖；筑基炼丹辅修可通过个人生产获得绑定凝核丹，金丹生产保持开放。筑基可由青石镇往返矿区，接取有效期内的云铁悬赏取得采集权限；QQ/OneBot 已从新角色通过正式修炼→移动→委托→采集云铁→生产→金丹突破链，并已由后续专项继续贯通元婴与化神；感气/聚气角色仍被拒绝。下一步转入炼虚之后的高阶境界。
38. **已完成（v0.3 元婴突破上游材料）**：金丹 L9 起在云舟抵达的深渊门完成魔界引导后，可每日最多 6 次备材探索取得神魂晶/魔核；金丹炼丹辅修可用神魂晶、灵叶和阵砂生产绑定凝魂丹（不可摆摊/拍卖/求购）。材料入口和受控金丹起点 QQ/OneBot 链已验收，已由新角色连续链覆盖。
39. **已完成（v0.1 新角色→筑基验收）**：QQ/OneBot 从新角色通过正式命令完成凡人引导、感气 L1→L10、聚气突破、采集和筑基丹/护脉丹生产、短历练积攒突破灵石、聚气 L1→L10 和筑基突破；全程未修改角色数据库。后续境界已由同一连续链继续验收。
40. **已完成（v0.1 道基质量来源）**：筑基成功将道基质量确立为原值与 5,500 的较大值，写入开始快照并保持历史 operation 幂等；失败不改质量。旧库只在首次升级时修复已筑基且质量为 0 的角色，不改非零值/低境角色。QQ/OneBot 新角色→金丹命令链验证了 0→5,500 并通过金丹道基门槛。
41. **已完成（新角色→金丹连续验收）**：QQ/OneBot 从创建角色开始不修改数据库，依次完成聚气、筑基、筑基静修到 L10、问安和短历练攒灵石、灵泉材料补充、矿区悬赏/云铁采集、凝核丹生产及金丹突破；后续第 42 条继续至元婴，第 47 条继续至化神。
42. **已完成（新角色→元婴连续验收）**：QQ/OneBot 从新角色沿第 41 条链继续，通过短历练/每日问安取得云舟及突破灵石、云舟试炼将金丹逐层修至 L10、深渊门引导与六次备材探索、凝魂丹生产、准备任务及元婴突破；不写入角色境界、修为、质量、灵石或背包夹具；后续完整链由第 53 条验收。
43. **已完成（元婴修为与化神许可来源）**：新增元婴 L1 起的神魂淬炼（每日 2 次、30 分钟、修为/神魂双收益）和界隙胜利神魂奖励；领域委托改为逐次交付魔核并逐次产出古果；远古洞天许可核验本人已结算的界隙胜利战斗编号，第三次事务扣除 3 枚神魂晶；化神许可发放魂种和突破用领域核心。伪造/重放、材料不足、每日限额及 QQ/OneBot 已验收；新角色的声望、灵石、世界功勋来源与化神突破已由第 47 条连续串测覆盖，后续完整链由第 53 条验收。
44. **已完成（魔界主线前置环修复）**：`quest.demon_main_1` 的两次遗迹探索证据现可由完成风险引导后的外层访问产生，主线完成后仍单独授予 `access.demon.fallen_ruins` 队伍副本权限；QQ/OneBot 均通过真实移动、探索和领取命令验证，且确认领取前未提前获得副本权限。此回归仍以元婴与 200 魔界声望为受控起点，作为魔界专项切片保留。
45. **已完成（魔界外层单人遭遇与队伍首领分离）**：确认自然资质玩家若在 `explore.demon_abyss` 遭遇 8000/520 魔渊领主必定无法形成两次主线证据；新增 `enemy.demon_ruins_scout` 与 `combat-0.3.1` 单人外层遭遇，保留 `enemy.demon_overlord` 原属性和 `combat-0.3.0` 版本供 2–5 人魔渊副本。QQ 官方与 OneBot V11 以自然资质、元婴突破并带有 600 点永久气血增量的属性快照完成外层两次探索和主线领取；新角色→炼虚的通用资源来源已由第 47 条覆盖，魔界专项仍以受控元婴起点验收。
46. **已完成（元婴三界主线真实入口）**：新增 `story.mainline.three_realms` 元婴 L1 玩家主线，调停/契约/共生三线每线 5 关且只能选择一线；开始与领取使用独立 operation，逐关写入 `quest_events`/`mainline_runs`，第五关事务发放对应三界声望 1000、`item.token.rebuild_path` 并写入 `story.mainline.three_realms` 旗标。界隙队伍可由该正式命令链获得主线证据；QQ 官方与 OneBot V11 已验收；后续完整链由第 53 条验收。
47. **已完成（新角色→炼虚连续验收）**：`test/test_progression_sources.py::test_qq_and_onebot_can_reach_dao_union_l10_from_new_player` 在 QQ 官方和 OneBot V11 独立数据库中，从新角色沿第 42 条链继续，使用正式命令完成三界主线 5 关、3 次领域委托、98 次万兽山队伍战、3 次界隙队伍战、跨界战、化神许可、每日神魂淬炼、元婴/化神逐层晋升、公开市场交易取得灵石、三次界壁试炼、档案航道/守卫、档案交付、炼虚许可和炼虚突破；抵达炼虚 L1 后世界功勋达到后续合道许可要求的 2,000。主角色未通过 SQL 写入境界、资源、资格或结果；协作者仅以受控高阶战斗属性和市场资金参与，队伍胜利、本人参与和市场结算证据均由服务端产生。测试随后沿第 48–52 条继续到合道 L10。
48. **已完成（新角色炼虚圆满续测）**：在第 47 条同一新角色链中，继续通过每日公开资源恢复、道历问安、每日两次神魂淬炼和境界晋升到炼虚 L10；QQ 官方与 OneBot V11 独立 SQLite 均达到境内修为 2,150,000、总修为 2,998,960，世界功勋仍不少于 2,000。后续第 49–53 条将该角色链延伸至飞升结局。
49. **已完成（新角色炼虚 L10 返程与合道挑战）**：在第 47、48 条同一新角色链中，炼虚 L10 从 `void.archive_ruins` 使用正式移动命令返回 `cave.boundary_realm`，无需已在早期消耗的一次性雾隐洞天凭证；随后正式开始并赢得合道个人挑战，写入该角色自己的资格事件。QQ 官方与 OneBot V11 独立 SQLite 均通过；没有修改主角色境界、背包、挑战结果或资格事件。
50. **已完成（新角色进入合道 L1）**：延续第 47–49 条同一角色，使用公开交易清出超容量背包并购买大师作品材料，通过正式命令完成三线共 30 关道源主线、三项辅修大师作品与合成作品生产/交付、合道主线证据、许可领取和合道入境。灵石、材料、境界、主线、挑战、生产及资格均由主角公开命令与服务端结算取得；受控协作者只提供市场资金和上架材料。QQ 官方与 OneBot V11 独立 SQLite 均通过，合道事务准确扣除 2,000 世界功勋、300,000 灵石和 10 枚绑定道果碎片。
51. **已完成（天劫凭证真实来源）**：合道许可领取事务发放 1 张绑定天劫凭证；三项当季道源任务各在 3/3 完成时发放 1 张，覆盖天劫台移动和三次试炼的总需求。QQ 官方与 OneBot V11 回归验证来源 operation 幂等、背包入账和禁止摆摊；凭证来源测试 3 项通过，新角色/道源来源长测 2 项通过（105.59 秒）。
52. **已完成（新角色合道 L10）**：延续第 47–50 条同一角色，QQ 官方和 OneBot V11 独立数据库各自通过正式 `开始修炼 神魂淬炼`、`结算修炼`、`晋升境界` 命令推进 600 万境内修为并逐层到合道 L10；资源恢复与日限按 650 天以内的虚拟时钟模拟，不修改主角色境界、境内修为或总修为。总修为达到 8,998,960，专项双适配器测试通过，耗时 169.49 秒。道源任务及渡劫/终局后续由第 53 条完整链验收。
53. **已完成（新角色至飞升结局完整链）**：QQ 官方与 OneBot V11 在独立数据库中，从新手角色起通过公开命令完成合道 L10 道源任务、渡劫 L1→L10 逐层修炼、身心/三界/道果三劫、天劫台飞升凭证生产、终局自动战和飞升选择。L9→L10 资格在任务进度跨越赛季后，仍按三项任务各 3 次成功事件共同属于至少一个历史赛季核验。专项双适配器测试 `test/test_progression_sources.py::test_qq_and_onebot_can_reach_dao_union_l10_from_new_player` 通过，耗时 221.38 秒；完整状态与仍待事项见[当前开发状态](current-status.md)。
54. **已完成（魔渊常规污染恢复与魂元丹来源）**：新增 `recipe.pill.soul_restore` 运行时配方，要求元婴、炼丹辅修和洞天二层炼丹房，消耗神魂晶 2、兽血 1、精力 15，生产 5 分钟、每日 3 次；新增 `净化污染` 独立 production operation，每次消耗 1 枚魂元丹并最多降低 20 点污染。污染 80 阻断、材料不足、污染为零、待处理心魔和 operation 重放均保持原子/幂等；QQ 官方与 OneBot V11 分别验证净化后魔渊探索恢复及资产隔离。
55. **已完成（炼虚失败后的公开灵石补给验收）**：失败会话、虚空不稳定冷却和结算 operation 重放保持幂等；再次突破前，主角色通过公开摆摊出售已结算航道/界壁试炼产出的虚空晶，反向适配器协作者通过公开购买提供灵石，未再 SQL 写回主角色钱包或功勋。QQ 官方与 OneBot V11 独立数据库均验证主角色世界功勋余额、协作者钱包和物品隔离；世界功勋耗尽后的公开来源补给仍列为下一步缺口。
56. **已完成（炼虚失败后的公开世界功勋补给验收）**：QQ 官方与 OneBot V11 独立数据库均将主角色功勋控制在恰好支付一次失败突破费用的 500，失败后确认余额为 0；冷却后由主角色通过五个独立领域前线轮次参与服务端领域战、投影本人战斗 operation 并领取每轮 100 世界功勋，累计 500 后发起并成功结算第二次炼虚突破。SQL 仅建立领域活动所需的测试角色境界/属性、宗门/地点和恢复会话材料前置，不写事件贡献、领奖、功勋或突破结果；突破重试的虚空材料作为受控测试前置。测试验证奖励物品、功勋余额及突破境界，完成炼虚失败的灵石/世界功勋公开来源补给闭环。
57. **已完成（v0.1 秘境试炼）**：新增独立 `secret_realm_models`、`secret_realm_rules`、`secret_realm_repository`、`secret_realm_use_cases` 与迁移表；开放 `instance.secret_realm.mist_grotto` 和 `instance.secret_realm.spring_path`。进入事务锁定体力/门票并冻结地点、境界、路线、内容/规则版本；节点强制 `resource -> encounter -> choice`（灵泉小径为两节点），遭遇复用服务端自动回合，失败不重抽资源，过期/失败按合同释放或消耗锁定资产，首通唯一且 operation 幂等。QQ 官方与 OneBot V11 双适配器专项覆盖门槛、节点跳跃、真实胜负、失败退票、过期恢复和角色隔离。
58. **已完成（v0.2 秘境试炼）**：新增 `instance.secret_realm.mist_depth_2` 和 `instance.secret_realm.cloud_boat`；雾隐洞天二层使用金丹 L1/地点/进阶门票门槛与五节点路线，第二场遭遇按 `run_id/node_index` 生成独立战斗 operation，首通事务创建云纹剑装备实例；云舟秘境使用云舟地点/票券门槛并在首通事务写入图鉴和地方名望。两项均支持内容/规则版本快照、周限额、资源锁、失败/过期恢复、首通唯一、operation 回放及 QQ 官方/OneBot V11 双适配器验收。

60. **已完成（v0.1 特色玩法：挂机收益）**：新增独立 `idle_models`、`idle_rules`、`idle_repository`、`idle_use_cases` 与迁移表；开放城镇跑腿、药圃看护、工具/作坊看守和商路观察四条路线。分配时冻结路线池、地点、成本、工具耐久、设施、服务端时间、完整/最大领取窗口和版本；领取按服务端 Clock 在完整窗口或超时最低保底结算，工具耐久只在成功完整领取时扣除。60 秒取消原子返还成本，长时会话与闭关/生产/移动/探索/战斗互斥；重复 operation、提前领取、超时、时间篡改、收益边界、QQ 官方/OneBot V11 身份隔离均有专项测试。
61. **已完成（v0.1 特色玩法：派遣任务）**：新增独立 `dispatch_models`、`dispatch_rules`、`dispatch_repository`、`dispatch_use_cases` 和迁移表；开放城镇送货、药材搜寻、作坊帮工。接受事务原子校验前置和成本，冻结角色/地点/道途、风险池、抽取结果、奖励、开始/结束时间与版本；单角色单槽、60 秒全额取消但仍计每日接受配额、延误固定 +50%、失败按合同返 2 体力或 1 木材。独立事务提供预览/接受/取消/结算、并发约束和 operation 回放；与挂机、移动、探索、修炼、生产、突破、战斗互斥。结束超过 24 小时的会话由 runtime 恢复循环以 assignment 派生稳定 operation 自动结算，settled event 同事务供七日入道 D6、首次派遣功业和称号使用；运行时 shutdown 会取消循环。近郊采集以 `exploration-0.1.1` 新增 10% 木材来源，并按旧探索快照版本保留 `0.1.0` 会话奖励。QQ 官方与 OneBot V11 正式命令测试覆盖三个任务、成功/延误/部分/失败、资源来源和退款、配额防重抽、并发槽位、超时恢复、routine/功业领奖、奖励边界、幂等与身份隔离。
62. **已完成（v0.1 特色玩法：图鉴收集）**：新增独立图鉴规则、模型、投影、查询/领奖 repository、里程碑快照和迁移表；新手问道/引导移动、材料奖励/灵田收获、异兽胜利、道途选择、公开竞技场快照、挂机、派遣、已接入秘境与竞技场来源在各自结算事务内写入图鉴。`我的图鉴` 支持分类/关键词查询，`领取图鉴里程碑` 使用 operation 幂等领取且未达成/重复领取拒绝；第五条首见 operation 接通 `achievement.codex_5`，地点三览真实解锁灵叶额外委托，普通与组队竞技场按对手公开快照记录其道途；试炼塔和 `story.xuantian.road` 三分支结局也分别在正式领奖事务写入挑战/故事分类首见。QQ 官方与 OneBot V11 模拟适配器覆盖正式查询/领奖、真实修为推进/地点来源、对局观察、未达成/重复领取、委托解锁和 repository 边界；展示徽记/路线提示不产生数值强度。
63. **已完成（v0.1 特色玩法：雾隐试炼塔）**：新增独立塔层模型、版本规则、迁移、事务 repository 和 application 用例；接通 `试炼塔`、`挑战试炼塔 <1-30>`、`领取试炼塔奖励`。接入 `pve.tower` 服务端自动战，独立发奖并屏蔽战斗域普通掉落/修为；实现 1–30 层首通、15/20 层配方线索、25/30 层洞天路线提示、重复练习图鉴观察、境界门槛、层段每日额度、每层每周练习额度、体力扣除、长行动互斥、D5/十层功业/称号和图鉴来源。失败启动退还体力且不占用额度；战斗中断后同 operation 可在 runtime 重启后续跑；结算/领奖保留塔局冻结版本。QQ/OneBot 覆盖 5/10/15/20/25/30 层首领、十层功业、战败、日/周额度、三个境界段 L3/L4 准入边界、全部特殊奖励领奖、练习观察、首通、互斥与重放；QQ 覆盖启动失败补偿，OneBot 覆盖重启恢复；新增塔 repository 边界断言。

64. **已完成（v0.1 特色玩法：玄天之路多结局剧情）**：新增独立故事规则、模型、SQLite 迁移与 `StoryRepositoryMixin`，接入 `剧情线`、`开始剧情`、`选择剧情 <商路|守望|药圃>`、`领取剧情结局`。开始要求寻仙问道；商路要求 3 次已交付委托、守望要求 2 场已结算胜利、药圃要求 2 次收获或 2 次成功药材派遣。选路事务冻结来源 operation 和完成节点并锁定单一结局；领奖事务原子发放 +10 青石镇名望、故事图鉴与外观/剧情旗标，不改修为和终局状态。所有阶段复用 operation ledger，结局唯一。QQ 官方与 OneBot V11 的模拟适配器各覆盖三条来源路径、未达成拒绝、同路线重放、异路线冲突、来源快照、领奖幂等/唯一和奖励边界。
65. **已完成（v0.3 界隙裂隙队伍秘境）**：新增独立 `boundary_rift` 规则、DTO、迁移和 `BoundaryRiftRepositoryMixin`，不扩充通用 `repository.py`；开放专用 `secret_realm_boundary` 队伍类型、`instance.secret_realm.boundary_rift` 六节点路线、两场服务端自动战、UTC 周额度、逐角色首通和 `codex.route.boundary` 投影。进入/顺序/节点战斗/结算使用独立事务及 operation，支持战败和过期按合同保留成本、战斗启动故障退款并释放额度、重启续跑、行动锁和退出保护。QQ 官方与 OneBot V11 双方向混合队伍覆盖准入、2–5 人队伍边界、首通/重复奖励、失败、过期、额度、恢复和补偿；兼容回归 28 项通过。

66. **已完成（v0.6 首条线索驱动遗府）**：新增独立 `legacy_manor` 规则、DTO、迁移、`LegacyManorRepositoryMixin` 与 application 命令，不向通用秘境仓储或 facade `repository.py` 增加业务事务。`instance.legacy.demon_reliquary` 要求元婴 L1、堕落遗迹地点/权限和既有绑定契约线索；三节点、无资源成本、60 分钟，失败/过期可重试，首通只写故事旗标。QQ 官方与 OneBot V11 覆盖准入原子拒绝、节点顺序、幂等冲突、资产不变、状态查询、重启身份切换、过期、系统中止、长行动锁与 operation 写入故障回滚。
67. **已完成（v0.6 第二条线索驱动遗府）**：将遗府规则按稳定 `instance_key` 配置化并在 `legacy_manor_runs` 增加兼容迁移字段；开放 `instance.legacy.demon_abyss_echo`，消费方只读取魔界深渊秘境既有的绑定线索，不改变其来源或资产语义。筑基 L1、深渊门地点/权限、三节点、60 分钟、零资源成本，首通只写故事旗标；与首条遗府共用一个活动锁和事务引擎，旧首条 operation 哈希保持兼容。QQ 官方、OneBot V11 分别覆盖准入原子拒绝、路线、幂等、跨适配器身份恢复、资产隔离、迁移及遗府间活动锁。

68. **已完成（v0.2 特色玩法：雾隐试炼塔 31–45 层）**：扩展金丹 L3 段普通/首领敌人、10 体力和 31–45 层段每日 3 次配额；首通固定发灵石 60、阵砂 2，35/40/45 层另发基础配方线索并投影楼层图鉴。SQLite 兼容迁移扩展楼层约束且保留历史塔局、领奖外键；1–30 层继续使用原内容/规则版本及 operation 哈希。QQ 官方与 OneBot V11 覆盖金丹门槛、31/35/40/45 层战斗快照、奖励/图鉴、层段日限、迁移和旧 operation 重放。
68a. **已完成（玄天主线扩章）**：主线定义迁入 `data/剧情/主线.json`，关卡、别名、前置、境界门槛和奖励由 `ContentBundle` 严格校验并由仓储按当前内容包消费；在既有首章和城镇委托之后接入云城、云铁、阵堂各三关。开始/领取继续复用 `mainline_runs` 与 operation ledger，首通/重试奖励、资产流水、图鉴事件、内容关闭、重复请求和输入冲突均保持原子；QQ 官方与 OneBot V11 双适配器覆盖完整路线，临时内容包变更可改变实际奖励。

69. **已完成（v0.3 特色玩法：三界塔 1–20 层）**：新增独立 `three_realms_tower_rules`、DTO、SQLite repository mixin 与 application 用例，共用兼容塔记录表而不把新塔事务并入雾隐塔或通用 facade。开放元婴 L1/三界主线许可、12 体力、每角色/层/UTC 周最多 2 次、顺序首通/领奖、练习、三阵营稳定首领键、楼层与阵营故事图鉴及固定版本快照；战斗奖励为空且领奖只允许灵石/阵砂。QQ 官方与 OneBot V11 覆盖 1–20 层完整推进、10/20 层战斗/领奖快照、门槛、失败计次合同、周限、幂等、图鉴和资产隔离。
70. **已完成（v0.4 特色玩法：三界塔 21–40 层）**：沿用专属规则和 repository mixin 扩展单人塔命令至 1–40；21–40 层开放化神 L1 或三类地区重建名望合计 500 的准入，每层 12 体力及 UTC 周 2 次，30/40 层使用三阵营首领并记录阵营故事图鉴，40 层首通来源授予展示称号。每层图鉴、失败/启动补偿/练习/领奖、普通战斗奖励隔离和双版本快照已接入；1–20 层 operation 哈希及 `content-0.3` / `specials-0.3.0` 历史记录保持兼容。QQ 官方与 OneBot V11 覆盖高阶完整推进、499/500 名望边界、旧主线许可不绕过门槛、失败计次、启动退款、周配额、快照、图鉴、称号、幂等和资产隔离。
71. **已完成（v0.4 特色玩法：三界塔双人规则）**：新增 `three_realms_tower_duo` 队伍类型、独立双人塔运行/成员奖励表和专属 repository/application。两名已确认同地点成员分别校验境界或 500 重建名望、分别扣 12 体力和计 UTC 周次数；启动时冻结成员构筑、技能、属性、阵营/盟约、三界名望、污染和血脉，复用服务端自动回合但关闭普通队伍奖励；失败不发奖，战斗启动故障全额退款，成员使用独立 operation 分别领取首通/练习奖励。QQ 官方与 OneBot V11 混合适配器覆盖第三人拒绝、门槛、体力/周限、快照、奖励隔离、失败、重启恢复和幂等。

71. **已完成（v0.4 常驻经营来源）**：沿用独立 `ProjectRepositoryMixin` 扩展 `project.domain_refuge`、`project.abyss_purification` 和 `project.ancestral_habitat`；三个项目按宗门/城市授权或魔界/妖界贸易站名望按需物化，材料与服务贡献按 UTC 日 30 点限额，完成后唯一发放对应地方名望、信誉和不可交易建设券。运输只认已结算运输，净化只认成功污染净化，驯养/修复只认本人成功的灵兽结缘/喂养/休养，来源凭证按角色唯一使用并在同一事务内核验。QQ 官方与 OneBot V11 覆盖门槛、来源归属、材料扣除、缺料原子拒绝、跨周、重启恢复、个人结算选择和 operation 重放。
72. **已完成（v0.4 领域前线主线）**：主线解析与仓储按 `story_key` 复用同一套关卡、运行记录、快照和 operation 账本；新增 `story.mainline.domain_frontier` 守界、净渊、护祖三线各六关。关卡前置读取领域前线已结算参战、战斗、贡献和领奖证据，三条结局分别发放公共项目权限、地方名望与服务信誉，不改领域能量；结局权限接入既有公共项目准入。QQ 官方与 OneBot V11 覆盖真实事件证据、三线完整推进、重复领取、operation 冲突、恢复后的快照和权限投影。
73. **已完成（虚空档案主线）**：沿用内容包驱动的主线解析、`mainline_runs`、服务端证据仓储和 operation 账本，接入记录者、护航者、归乡者三线各八关。炼虚 L1 与档案解锁为共同前置；档案守卫胜利和时序堡垒首通分别作为服务端证据，不能由请求参数伪造。首通只写图鉴并发放灵石，明确禁止虚空晶、虚力、突破资格和终局状态写入；QQ 官方与 OneBot V11 覆盖三线推进、证据时序、重启恢复、幂等、输入冲突和奖励边界。
74. **已完成（公共项目内容合同闭合）**：将六条地方公共项目及运输、净化、驯养、修复服务来源迁入 `data/生活/生活.json` 的 `public_project` 记录；`public_project_definitions()` 统一校验稳定键、资产引用、权限阈值、奖励和来源 operation，repository/application 显式复用宿主内容包。临时内容覆盖会改变实际奖励/阈值，坏引用明确失败；既有 QQ/OneBot、幂等、重启恢复、来源唯一使用和资产原子性测试继续复用。子代理仅负责规则与内容合同审计，未复制事务或引入兼容分支。
75. **已完成（虚空塔道源与登临路线）**：将 `tower.void_spire` 61–75 层道源路线和 76–90 层登临路线登记到内容包，包含渡劫/道统服务准入、每段周限、30 体力、敌人稳定键、首领、故事图鉴、展示称号和首通/重复奖励；SQLite 塔局约束扩展至 90 层。运行时按当前内容包读取路线、敌人、成本和奖励，仍复用真实 `pve.tower` 自动战、资产事务、图鉴投影和 operation 账本；QQ 官方与 OneBot V11 覆盖首领首通、重复请求、内容覆盖、双适配器、启动故障退款和重启恢复。子代理只完成合同与测试审计，未复制事务逻辑。
76. **已完成（基础属性推演与快照切片）**：新增 `stats.formula` 内容记录，由内容包严格校验六项资质、境界层数、派生属性和软上限；`我的属性`、`属性说明` 和资料卡复用同一整数推演函数。`stats.freeze` 以 operation 账本写入不可变 `stat_snapshots`，同一输入重放原快照，不同用途冲突，重启后可恢复；内容规则改值会改变新的推演和内容指纹。QQ 官方与 OneBot V11 已覆盖预览、解释、快照、重放、冲突和 JSON 改值。该切片只统一基础属性查询与快照，不把尚未闭合的装备/天赋乘区写入第二套规则；训练傀儡仍为只读观战，正式战斗沿用各自已验收的开始快照边界。
77. **已完成（寻仙问道基础奖励内容化）**：新增通用奖励解析器，严格校验灵石、物品、角色数值、数值上限和来源 operation；`reward.onboarding.seeking` 由内容包读取后交给统一角色状态事务，实际奖励快照写入 `player.start_seeking` operation。QQ 官方与 OneBot V11 覆盖临时内容改值、资产/数值原子发放、重复 operation、输入冲突和重启恢复；其他固定奖励仍待后续切片迁移。子代理仅做奖励合同与既有通用内核的只读审计，事务实现和测试收敛由主线完成。

78. **已完成（灵泉事件奖励内容化）**：灵泉事件领取从事件记录引用的基础奖励与完成加奖读取 `data/奖励/奖励.json`，失败轮次只发基础奖励，成功轮次合并完成加奖；灵石、物品、修为/总修为和阵营声望在同一角色状态事务中写入。operation 同时冻结基础、完成和最终奖励快照，重复请求、输入冲突、跨适配器领取、失败轮次、过期窗口与重启恢复均按原结果处理。子代理负责候选切片、奖励合同与复用边界审计，并补充专项测试；主线复核事务边界、双适配器路径与最终收敛，未复制领域逻辑或引入旧路径。

79. **已完成（近郊短历练奖励内容化）**：`explore.trial_outskirts` 的修为与灵石加权池迁入 `data/奖励/奖励.json`，统一加权选择器校验奖励池、物品引用和正整数权重；探索开始事务冻结奖励池键、种子与实际结果，结算沿用探索自动战，胜利发放冻结奖励，失败不发探索奖励，战斗域不重复发放。奖励结算继续复用角色状态事务、修为总量同步和资产读取，声望分支也改走统一声望增量入口。QQ 官方与 OneBot V11 覆盖内容改值、启动后内容变更、双适配器、战斗胜负、重启恢复、operation 重放与输入冲突。子代理分工写入本条：A 审计探索合同与 JSON 引用，B 审计奖励/资产/玩家状态复用边界，C 审计双适配器、恢复和失败/成功测试；主线负责仓储事务、快照和最终收敛。

80. **已完成（近郊采集奖励内容化）**：`explore.gather_outskirts` 的止血草、铁石和木材联合加权池迁入 `data/奖励/奖励.json`，以联合结果保留原三次独立抽取的概率分布；开始事务冻结奖池键、种子和实际物品结果，普通结算与遭遇战结算均复用 `utils.player.split_player_rewards` 和角色状态事务，战斗域不重复领奖。双适配器覆盖内容改值、停机恢复、成功/失败遭遇、重复 operation 和输入冲突；零数量可选物品不写入结果，物品显示名从当前内容包读取。子代理 A 审计合同并补联合概率与非法池测试，B 实现通用奖励分流及边界测试，C 补双适配器、恢复与真实遭遇胜负测试；主线整合内容、仓储与文案，负责最终验证、提交和推送。其他探索模式和领域奖励分流继续逐条迁移，不扩展只读切磋或傀儡的写入边界。

本条回归收尾：公共事件投影仅读取共有字段，灵泉奖励快照由灵泉入口显式传入，不为其他事件增加兼容分支。魔渊败退测试固定探索编号以重放真实战斗种子，补齐 QQ 官方与 OneBot V11 的无奖励、体力扣除、神魂疲劳和重复结算断言，不修改正式战斗规则。收尾子代理只读审计随机来源与夹具；主线负责复现偶发胜利、修复测试、验证及提交推送。

81. **已完成（灵泉采集奖励内容化）**：`explore.spring_gather` 的灵叶、阵砂和灵泉水迁入 `reward_pool.exploration.spring_gather`，四种联合结果保持原独立抽取概率；复用奖励池解析、开始冻结、角色状态事务和灵泉事件贡献投影。内容改值、重启后旧奖励恢复、新会话读新内容、无叶/过期不贡献、轮次边界、并发与 operation 重放、非法内容原子拒绝、贡献/图鉴投影异常回滚，以及 QQ 官方/OneBot V11 均有测试；采集保持无战斗遭遇。子代理 A 实现双适配器恢复、贡献和回滚测试，B 审计合同并参数化概率、重载和非法池测试；主线实现内容消费、长链夹具收敛、文档和最终验证、提交推送。文档登记的 15% 资源事件尚未接入探索运行时，后续单独按完整事件合同处理，不与奖励池混同。

82. **已完成（雾隐洞天探索奖励内容化）**：将 `explore.mist_grotto` 的修为、材料种类和数量联合分布迁入奖励内容包，按探索开始快照冻结结果，普通结算和真实精英遭遇均复用角色事务。聚气 L4、地点/会话前置、每日限额与 25% 遭遇规则不变；子代理 A 覆盖双适配器内容变更、重启、真实胜负和幂等，B 审计 27 种联合概率、内容引用和非法奖池；主线接入消费、更新领域合同并完成收敛。专项 99 项、文档 2 项及全量 748 项测试通过，JSON 校验、`compileall` 与 `git diff --check` 通过。后续探索奖励迁移仍按独立垂直切片推进。

83. **已完成（云铁矿区采集奖励内容化）**：将云铁 1–4 的原有权重迁入当前奖励内容包，开始时冻结正常收获和内容定义的战败保底；保留筑基、矿区许可/采矿资格、体力/精力成本、每日限额及 30% 矿兽遭遇。战败奖励作为奖池可选字段，经共享奖励校验与探索域数值边界检查，并随探索/战斗状态一起恢复；结算复用原角色事务和自动战斗。QQ 官方与 OneBot V11 覆盖内容变化、重启、真实胜负、中断恢复、operation 重放、输入冲突、坏引用与拒绝回滚。专项 120 项、文档 2 项和全量 784 项测试通过，JSON 校验、`compileall` 与 `git diff --check` 通过。后续洞天二层、云舟试炼及三界探索奖励继续逐条迁移。

84. **已完成（洞天二层探索奖励内容化）**：将修为与云铁的独立抽取展开为六种联合结果，按原 30/45/25 与 60/40 分布写入 `reward_pool.exploration.mist_grotto_2`；探索开始时冻结实际结果，普通结算与 `enemy.mist_elite` 自动战沿用同一角色事务，战败不发探索奖励。金丹 L1、已抵达二层、15 体力、每日两次和 40% 基础遭遇保持不变。QQ 官方与 OneBot V11 覆盖联合概率、内容变化、重启恢复、胜败、幂等、输入冲突和坏引用拒绝。子代理 A 审计规则合同、精确概率与领域引用；子代理 B 审计双适配器恢复和真实战斗测试路径；主线负责奖池接入、消费边界、领域文档及最终验证。云舟试炼与其他尚未迁移的探索奖励继续各自按独立切片处理。

85. **已完成（云舟试炼奖励内容化）**：将修为与云舟票碎片的独立抽取展开为六种联合结果，按原 30/40/30 与 60/40 分布写入 `reward_pool.exploration.cloud_boat_trial`；开始时冻结基础收获，风暴等待沿用冻结结果，支付在冻结修为上增加现行加成，返航不发收获。QQ 官方与 OneBot V11 覆盖联合概率、内容变化、重启恢复、风暴选择、幂等和输入冲突。子代理 A 审计云舟奖励合同、风暴与快照边界；子代理 B 审计物品/灵石事务和玩家数值读取的共用内核，确认本切片复用 `grant_player_state` 与既有玩家投影，并检查切磋、训练傀儡仍只读；子代理 C 审计运行时代码及测试中的版本标识，主线完成移除、奖池接入、双适配器测试、文档与最终验证。三界探索奖励仍按独立切片迁移。

86. **万兽山狩猎奖励内容化**：稳定键 `reward_pool.exploration.beast_hunt` 提供兽血 45、妖界声望 30、绑定血脉线索 15、明确无收获 10；无收获不创建祖灵事件，福缘权重只提升物品结果。探索开始时冻结内容奖池键与实际结果，QQ 官方/OneBot V11 覆盖配置变更、停机后恢复、真实自动战胜败、幂等/冲突和坏引用原子拒绝。子代理 A 只读审计奖励合同、原分布与跨界规则，子代理 B 只读追踪双适配器、operation/恢复和真实 PvE 路径；主线统一实现 JSON 消费、共享奖池解析、状态事务与文档，未复制 application/repository 逻辑。魔界堕落遗迹和祖灵湖探索奖励继续作为后续独立切片。

87. **魔界堕落遗迹探索奖励内容化**：稳定键 `reward_pool.exploration.demon_abyss` 提供魔核、魔界声望、绑定契约线索与明确无收获分支，并由内容字段声明是否采用福缘物品权重加成。探索开始冻结奖池键和实际结果，跨适配器验证内容改值、停机恢复、operation 重放/冲突、坏引用原子拒绝、真实胜败与无收获胜局；保留污染增加、败退神魂损耗/疲劳和主线战斗证据。子代理 A 只读审计奖励合同、原分布和规则边界；子代理 B 只读审计双适配器、恢复与战斗测试缺口；主线负责 JSON 消费、共享资产事务复用、专项测试、领域文档和最终验证，不复制 application/repository 逻辑或加入版本/兼容分支。祖灵湖探索奖励继续作为下一条独立切片。

本节按首次验收阶段保留编号记录；其中早期“仍待”描述为当时快照，后续进展以本节后续条目和[当前开发状态](current-status.md)为准。

第 12 条末尾的“完整技能系统仍未开放”属于切片前历史描述，当前以第 13 条的技能快照与复起实现为准。

88. **已完成（祖灵湖探索奖励内容化）**：稳定键 `reward_pool.exploration.ancestral_lake` 以单一结果保留祖灵血 1、妖界声望 30；不启用福缘权重加成或战败保底。化神 L1、妖界声望至少 3000、血脉稳定至少 50、每日两次、25 体力、20 分钟、35% 自动遭遇与每次最终结算稳定度下降 5 均保持现行行为；普通完成及真实战斗胜利发放开始时冻结的结果，败退不发探索奖励。QQ 官方与 OneBot V11 覆盖配置改值、停机恢复、新会话读取新内容、开始/结算 operation 重放与输入冲突、坏引用原子拒绝、稳定度门槛以及真实 PvE 胜败。子代理 A 只读审计规则与内容合同，子代理 B 只读审计双适配器、operation、恢复和真实战斗测试缺口；主线统一接入 JSON 奖池、复用既有奖励解析和角色事务、更新领域文档并执行最终验证，不复制 application/repository 逻辑，不加入版本标识或兼容分支。

89. **已完成（深渊门备材奖励内容化）**：稳定键 `reward_pool.exploration.demon_threshold` 以单一结果保留神魂晶 1、魔核 1；不启用福缘权重或战败保底，且本模式无战斗遭遇。金丹 L9、深渊门、魔界引导旗标、每日 6 次、4 分钟、8 体力与 2 精力均保持现行规则，结算继续为魔核生成 24 小时绑定流水。QQ 官方与 OneBot V11 覆盖冻结/重启恢复、内容变更后新会话读取新值、开始/结算 operation 重放与冲突、坏引用拒绝、体力/精力不足原子拒绝和材料绑定。子代理 A 只读审计运行合同、引导与资产引用，子代理 B 只读审计双适配器、恢复和测试覆盖；主线统一接入 JSON 奖池并复用共享解析与既有角色事务，不复制 application/repository 逻辑，不添加版本标识或兼容分支。

90. **已完成（引路任务奖励闭环）**：`引路簿` 和 `领取引路嘉奖 <任务名>` 从 `data/任务/任务.json` 读取四项常驻任务、名称和触发条件，从奖励内容读取实际奖励；来源必须是本人成功寻仙/入道 operation、成功近郊采集结算或成功生产订单结算。奖励、来源事件、任务进度和 operation ledger 在同一事务提交，重复领取受角色/任务唯一进度保护，内容变化不改重放快照。QQ 官方与 OneBot V11 覆盖真实来源、内容改值、坏奖励引用、注入故障回滚、输入冲突、重启重放以及战败采集/失败生产不达标。子代理 A 只读审计任务/奖励合同、来源证据与观战边界；子代理 B 只读追踪 repository、operation 恢复和双适配器测试入口；主线实现并收敛 application/repository 与测试，没有复制事务或新增版本/兼容路径。

91. **已完成（角色状态读写复用收敛）**：玩家灵石、背包、数值、阵营声望统一走 `utils/assets.py` 与 `utils/player.py` 的校验、增减和同事务写入；混合奖励先由 `split_player_rewards` 分流资产、数值和声望，组队战、深渊秘境、公共事件及秘境奖励共用这条分流路径。角色资料、状态展示、探索/战斗开局共用归一化投影；妖界/魔界引导、公共事件、秘境、悬赏和队伍奖励不再手工解析并回写阵营声望 JSON，玩法差异仍由领域负责。聚焦测试覆盖错误声望值拒绝、资产/数值/声望一次提交、双适配器领奖重放、探索与真实 PVE 结算。子代理 A 只读盘点资产增减及可复用入口，子代理 B 只读追踪资料/状态/战斗读取与测试入口；主线统一改动和验证，没有让适配器复制事务逻辑。该整理不补写尚无完整规则合同的灵泉资源事件或每日任务。

92. **已完成（三界公共事件规则与结算收敛）**：魔界入侵、妖界贸易和界隙裂痕的轮次、全服目标、贡献来源参数、个人门槛及奖励引用从事件/奖励 JSON 读取；贸易键须在地点开放动作中登记，队伍类型列表、物品和声望资源字段均校验。新轮次冻结配置与奖励，重启后仍按原快照验证来源及领奖；后续轮次读取当前内容。三类奖励复用角色资产/数值事务，魔界战场移动和正式自动战开局共用当前事件时间窗判断。QQ 官方与 OneBot V11 覆盖内容改值、旧轮次重启领奖、坏引用事务回滚、贡献 operation 重放/冲突和实际 PVE 来源。子代理 A 只读审阅公共事件规则、奖励合同与来源证据；子代理 B 只读追踪适配器入口、operation 恢复和双适配器覆盖；主线统一修改 application/repository、JSON 与测试。切磋和训练傀儡仍是只读观战，不创建邀请、不写角色或图鉴状态、不扣资源、不发奖励。

93. **已完成（每日修行轮次）**：按现行 JSON 抽取并为角色冻结 UTC 日课、本人已结算来源 operation 白名单、奖励快照与次日截止；同一来源在一轮只能计入一项，进度不复用长期任务表，奖励与灵石/精力/地方名望在同一事务结算。统一 application 接入 `每日修行`、`领取日课嘉奖`，QQ 官方与 OneBot V11 覆盖真实问安/修炼/采集来源、失败/伪造/跨角色/训练战来源拒绝、配置变更冻结、日切与过期、重复领取/输入冲突、故障回滚及重启恢复。子代理 A 只读核验来源操作和结算结果，子代理 B 只读审阅适配器命令注册、回放恢复与测试缺口；主线复用角色资产/数值/声望事务并完成 application、repository、JSON、双适配器测试和领域文档。切磋与训练傀儡保持只读观战；正式 PvE/PvP 的结算流程未被日课改写。玩家可见文本不展示稳定键、请求编号或开发状态。

94. **已完成（角色状态内核复用第二阶段）**：将领域中重复的“奖励拆分后写入资产、数值和声望”收敛为 `utils.player` 的通用奖励应用入口，并迁移探索、队伍战、跨界秘境和三界主线等真实结算路径；物品发放/扣除、灵石增减继续由 `utils.assets` 的同一资产事务处理，角色资料、状态展示和战斗开局继续使用统一投影。子代理 A 只读审计物品/货币/数值读写重复点，子代理 B 只读核验真实 PvE/PvP 结算、重放与训练傀儡/切磋只读边界；主线负责工具函数、领域调用收敛、聚焦测试、文档和最终验证，不新增版本标识或旧入口兼容分支。`test_utils`、探索、队伍战、魔界遗府和三界主线聚焦测试通过。

95. **已完成（角色奖励事务复用第三阶段）**：奖励拆分和原子写入复用 `utils.player.grant_player_reward`，派遣、雾隐试炼塔、虚空塔领奖和正式竞技结算均不再手工改写地方名望 JSON；地方名望上限由调用领域明确传入，服务信誉按角色状态合同在共享内核中统一封顶。资产、数值、声望、图鉴和 operation 仍在原领域事务中提交，重放不重复变化。子代理只读审阅合同与复用边界，主线负责仓储迁移、封顶/回滚测试、QQ 官方与 OneBot V11 路径核验。其他日课、生活、师徒、剧情及部分活动仓储仍有直接声望写入，按各自事务逐条迁移，不改变其业务语义；道统服务见闻因缺稳定键、来源及奖励定义暂不扩写。不得加入运行时版本标识或旧格式兼容分支。

96. **已完成（灵木收获奖励内容化）**：`reward_pool.routine.spirit_tree_harvest` 将原灵石三档、种子概率与青石镇名望联合为 10,000 权重奖池；种子物品与地点名望上限均登记在当前内容包。收获沿用 operation 派生种子并冻结奖池键和实际结果，`grant_player_reward` 在一个 SQLite 事务内发放灵石、物品和封顶后的地方名望；重放不重新抽取。QQ 官方与 OneBot V11 覆盖内容改值、名望上限变化、重复 operation、重启恢复，故障注入覆盖奖励和收获记录写入后的完整回滚；奖池引用校验拒绝未知地点。子代理只读审阅奖池/地点引用合同，主线统一修改 JSON、解析器、仓储和适配器测试，没有复制事务代码或增加版本/兼容分支。

97. **已完成（灵田收获奖励事务复用）**：灵田收获把已冻结的背包收获与 `local.xuantian.new_town` 名望交给 `utils.player.grant_player_reward`，上限从当前地点内容读取；收获记录、材料图鉴、operation 与资产仍由原领域事务原子提交。地点测试将上限改为 41 并验证结果封顶；故障注入在名望写入处中止事务后，背包、灵田状态和 operation 均未变化，同一 operation 重试成功且重放不重复结算。QQ 官方与 OneBot V11 均通过灵叶和止血草命令路径验收。子代理分别只读审阅资产/角色投影复用和生活声望迁移候选；审计确认玩家背包/灵石写入及资料、状态、战斗投影已普遍使用共享内核，本条由主线迁移最后一处灵田奖励直写，不并行修改仓储。日课、运输、委托、师徒和剧情奖励仍按原领域事务逐条收敛，不新增版本标识或兼容分支。

98. **已完成（城镇委托交付奖励事务复用）**：城镇委托交付将已冻结的材料扣除、灵石报酬、地方名望和服务信誉交给 `utils.player.change_player_state`；业务日委托从开放地点内容冻结名望键及上限，接取复制原快照，服务信誉由共享内核封顶。共享名望封顶只限制正向所得，已有名望超过旧单上限时不扣回余额；结果和玩家回复记录实际增量。委托状态、结果、operation 与角色状态在同一 SQLite 事务内提交，名望、交付记录和 operation 三阶段故障均完整回滚，坏声望 JSON 明确拒绝。QQ 官方与 OneBot V11 的真实命令和重启测试覆盖内容改值、冻结上限/名望键、关闭禁新接取但旧单交付/重放、跨日接取重放、竞争交付、重复请求与输入冲突，云城商会专项也复用同一事务。子代理 A 只读审阅资产/角色投影复用和生活声望迁移候选，子代理 B 只读复核冻结、恢复及测试缺口，发现旧上限扣回余额和当前内容阻断历史重放两处边界；主线统一修复工具、仓储、名称解析、文案、JSON 与测试。协作约定已写入开发指南；不新增运行时版本标识或兼容分支。运输、公共项目、日课、师徒、剧情及其他活动声望写入仍按后续独立切片收敛。

本条身份解析验收保持委托稳定键、名称与别名不变；尚未覆盖删改旧名称/别名后的原文字请求重放。后续如允许此类调整，需统一冻结身份与请求解析合同，不增加旧格式回退。“下一条优先收敛短途运输”是当时的计划快照，现已由第 99 条完成。

99. **已完成（短途运输规则与奖励事务复用）**：运输规则从生活 JSON 读取并校验路线、起终点、允许阶段、货物价值/名称/别名、默认货物、成本、耗时、次数、延误和固定奖励，移除对应 Python 内容表。出发冻结货物、延误、灵骑、地方名望键及地点上限；结算用 `utils.player.change_player_state` 同时发放灵石、增加名望与更新目的地，灵骑状态/经验、路线结果和 operation 保持原领域事务原子提交。封顶不扣回已有名望，DTO 与玩家回复记录实际前后值和增量。历史开始/结算请求先读账本，内容关闭或改值不阻断旧运输结算/重放，新运输仍校验当前内容。子代理 A 只读审阅内容合同、资产复用、解析和事务边界；子代理 B 仅负责独立运输测试文件，主线负责运行时代码、JSON、文案、文档、审阅合并与最终验证。没有新增运行时版本标识或旧格式兼容分支；切磋和训练傀儡保持只读观战，正式 PvE/PvP 结算不变。

100. **已完成（闲居历练规则与奖励内容化）**：四条闲居路线的名称、别名、阶段/地点/名望/居所/工具门槛、耗时、成本、单路线每日结算次数、完整奖池和逾时奖池均由当前生活与奖励 JSON 提供并严格校验。开始时冻结路线名、实际双奖项、随机种子、地点名望上限、工具耐久及安排时刻；领取只按数据库时刻和冻结结果，通过共享角色奖励事务提交资产、名望、耐久、图鉴、安排与 operation。修复准入检查缩进，修正跨路线混用日限；坏 JSON、内容改值、重启重放、不同输入冲突、账本故障回滚/同 operation 重试、商道见闻和 QQ 官方/OneBot V11 均有聚焦覆盖。子代理只读审阅闲居合同/准入、事务与奖励复用边界、双适配器测试缺口；其结论供主线收敛，没有并行修改仓储或测试。主线负责统一 JSON 消费、角色状态事务接入、文案、测试和文档；闲居不写战斗或观战状态，切磋/训练傀儡仍只读，正式 PvE/PvP 结算未改写。

审阅额外发现未指定内容包时起点名称读取失败，以及当前货物名称变更会影响旧运输回复；主线以路线定义提供起点名称、出发快照冻结货物名称解决，并增加真实回复、缺失货物与坏名望 JSON 的拒绝/回滚验证。隐式货物只在新请求通过账本校验后解析，默认货物改值或移除不改变历史开始结果；货物数量拒绝布尔值、小数和字符串，阶段引用复用现有角色阶段合同校验。

运输身份重放验收保持路线和显式货物的稳定键、名称与别名不变；删改旧名称/别名后的原文字请求重放仍需后续统一身份冻结合同。公共建设对运输的延误减免数值、其他商路、日课、师徒、剧情的直接名望写入继续按独立切片迁移；公共项目奖励事务已由第 100 条完成。运输主动取消、失败与过期退货未实现，本条结算故障回滚不承诺返还出发成本。

本条验收：运输专项 50 项通过，生活、事件、工具与文档等聚焦组共 202 项通过；自动战斗、探索遭遇与队伍战另 17 项通过。`compileall`、全部 JSON 格式和 `git diff --check` 通过；本轮未运行完整新角色至飞升长链，不宣称全量通过。

上一切片验收收尾：修复灵泉活动结果记录遗漏 `minimum_contribution` 的查询/领奖异常；当前规则门槛写入结果快照，重放严格读取同一字段，不增加缺字段回退。当时完整回归两次停留在新角色至飞升长链，长链在 28 分钟后中止，不能标为全量通过；其余回归单独运行，结果在当前状态页保留。

100. **已完成（公共项目奖励事务与快照）**：六条公共项目在逐周物化时冻结名称、说明、需求、贡献资源、奖励、名望地点与地点上限、服务来源和成效文案；结算不再依赖现行项目奖励内容。灵石、物品、地方名望与行旅声望经 `utils.player.grant_player_reward` 统一提交，名望封顶后只记录实际所得，奖励记录与 operation 同事务；损坏的名望 JSON 明确拒绝，名望/领奖记录/operation 三阶段故障均验证完整回滚和同 operation 重试。内容变更或关闭不改已物化项目领奖及回复；列表、贡献和领奖文案改为中文地点/物资/成效/进境，不显示稳定键、内部状态或原始时间戳。重建名望统一归属领域前线、魔渊集市和三界贸易口地点内容，三界塔读取同一组地点名望。子代理 A 只读审计奖励合同、事务边界与既有共享工具；子代理 B 只新增独立 `test/test_livelihood_project_rewards.py` 覆盖内容快照、坏 JSON、冲突、回滚重试和 QQ/OneBot 事件；主线负责规则、仓储、共享状态读取、内容引用、文案、领域文档及最终验收，没有并行改动同一仓储，也没有新增版本标识或兼容分支。项目与共享状态专项 96 项、包含正式 PvE/PvP 及只读观战回归的聚焦组 137 项通过；`compileall`、全量内容 JSON 格式和 `git diff --check` 均通过。

101. **已完成（日课名望封顶与实际所得）**：日课规则从青石镇地点内容读取名望上限，并随 UTC 日轮次与奖励一同冻结；领奖不再按配置数量虚报名望，而是通过共享角色声望投影记录实际增量。已有名望超过上限时保留原余额，零增量不出现在领取记录或玩家回复；内容上限变更不影响已创建轮次。QQ 官方与 OneBot V11 覆盖上限前部分所得、超额余额、内容改值、缺失上限原子拒绝、故障回滚、operation 重放与重启恢复。该切片由主线实现并收敛；未并行修改仓储或测试文件，无需新增兼容分支或运行时版本标识。

102. **已完成（师徒毕业声望事务复用）**：毕业保留原关系事务与 operation 边界，徒弟名望和双方服务信誉改由 `utils.player.change_player_state` 统一校验、封顶与写入；青石镇名望上限读取当前地点内容，operation 与玩家回复冻结实际所得。畸形名望 JSON、奖励写入后的故障均令关系、声望、贡献和 operation 一并回滚；同 operation 重试成功，重启后重放不再结算。QQ 官方与 OneBot V11 覆盖地点上限改值、名望/信誉部分封顶、服务信誉已满、拒绝坏 JSON、事务回滚和恢复。子代理只读审阅共享状态复用候选和师徒事务/测试缺口；主线负责仓储、结果 DTO、玩家回复、双适配器测试与文档统一收敛，没有并行改动同一仓储或测试文件，也没有添加运行时版本标识或旧格式兼容分支。

103. **已完成（图鉴里程碑名望与历史领奖回放）**：里程碑 operation 先于现行内容解析，已成功的请求按历史奖励和展示快照重放；新领奖仍校验开放定义、见闻齐备与唯一领取，并通过 `utils.player.grant_player_state` 结算地点名望，上限读取地点内容。领奖记录、operation、回复和已领取条目的图鉴展示只保存封顶后的实际所得；坏名望 JSON 和 operation 写入故障均原子回滚，同一 operation 可重试。QQ 官方与 OneBot V11 覆盖自定义上限与奖励、部分封顶、内容关闭后的重启重放、坏 JSON、账本故障回滚及重试。两名子代理只读审阅图鉴/奖励合同、共享状态复用与恢复测试缺口，未修改工作树；主线独立完成仓储、结果快照、应用展示、专项测试和文档收敛，没有并行修改同一模块，也没有新增运行时版本标识或兼容分支。

104. **已完成（玄天主线地方名望事务）**：配置了地方名望奖励的主线关卡，开始时从 `reputation_key` 指向的地点内容冻结名望上限；领奖从运行快照恢复奖励和上限，地方名望、服务信誉及资产均通过 `utils.player.grant_player_state` 提交，主线结果与 operation 只保存封顶后的实得增量。运行中改值或关闭内容、停机重启、同 operation 回放不改变结果；坏名望 JSON、奖励后 operation 写入故障和损坏快照均不留下部分结算，原 operation 可在故障解除后重试。QQ 官方与 OneBot V11 覆盖内容改值、部分封顶、重启恢复、operation 回放、坏 JSON、故障回滚和同请求重试，聚焦测试 16 项通过。子代理只读审阅主线、行卷/道契名望候选及合同缺口；主线负责仓储、共享状态事务、恢复与双适配器测试和文档验收，未并行修改同一代码或测试文件，没有新增运行时版本标识或旧格式兼容分支。其他主线、剧情与活动声望仍逐条迁移。

105. **已完成（悬赏快照与领奖状态事务）**：接取事务冻结悬赏名称/说明、目标类型/键/数量、交付规则、奖励池键与实际奖励、资产展示名、装备实例模板、图鉴分类、地方名望键及地点上限、随机任务候选/权重与独立种子、选择输入和各类进度基线；榜单奖励预览按境界/道途筛选，进度与领取不再重新读取现行定义。每日次数按悬赏内容逐项计数，同一时间仍只允许一条未结/待领悬赏。内容奖励复用共享奖池校验和 `utils.player.split_player_rewards`，扣除/发放、数值、阵营/地方名望与服务信誉通过 `change_player_state` 同事务提交；装备实例、图鉴投影、悬赏状态及 operation 保持原领域边界，结果只记录精力和封顶名望后的实际所得。洞天二层精英补入活动敌人内容并由自动战读取，悬赏目标引用校验闭合。损坏快照、非法奖励类型及坏名望 JSON 均原子拒绝；提交账本故障后原请求可重试，成功和过期结果均可稳定重放。QQ 官方与 OneBot V11 专项覆盖内容改值及重启、封顶、快照/名望 JSON 损坏、operation 写入故障回滚与重试、装备/图鉴冻结、随机候选和每日次数；既有真实探索战悬赏仍通过双适配器验收。悬赏、冒险、战斗、奖励、图鉴、派遣、内容、文档及观战/PvP 回归所选测试共 294 项通过；`compileall`、全部内容 JSON 解析和 `git diff --check` 通过。两名子代理只读审阅悬赏合同、共享工具复用、故障测试及最终快照/配额/引用边界，均未修改工作树；主线负责实现、整合、双适配器验收和最终复跑，没有并行修改同一仓储或测试文件，没有新增运行时版本标识或旧格式兼容分支。协作方式按任务边界选择，不要求每条切片强行拆分。

106. **已完成（玄天之路内容与结局结算收敛）**：新增故事内容记录，分支、门槛、来源键、完成经历和展示文案从内容包读取；结局奖励及三条故事图鉴条目均登记在当前内容包。选路冻结来源 operation、分支展示、奖励、名望地点及上限、图鉴类别、旗标和居所外观；领奖不再读取当前故事/奖励/图鉴定义，由 `utils.player.grant_player_reward` 与结局记录、图鉴发现和 operation 同事务提交，结果及玩家回复只记录封顶后的实得名望。内容关闭、坏名望 JSON、注入账本故障回滚与重试、内容改值、重启恢复及 operation 重放由 QQ 官方和 OneBot V11 覆盖；训练傀儡和切磋仍是只读观战，正式 PvE/PvP 结算保持原路径。子代理只读审阅发现结局仍直写名望且故事/图鉴定义缺失，没有修改工作树；主线完成内容、规则、仓储、用例、适配器测试和文档收敛，没有复制事务逻辑或加入运行时版本标识/旧格式兼容分支。剧情规则及适配器专项 3 项通过。

107. **已完成（七日入道 D4/D7 名望事务）**：D4 悬赏接取与 D7 入道 operation 仍是本人服务端来源；两个名望奖励现在按青石镇地点内容上限经 `utils.player.grant_player_reward` 与背包资产、领奖记录和 operation 同事务提交，记录/回复只保留封顶后的实得名望，已有名望超过上限时不扣回。QQ 官方与 OneBot V11 均覆盖两条真实来源及不同余额下的封顶；临时内容把地点上限改为 6 并在重启前再改为 20，证明实际所得随内容变化而历史 operation 回放不变。坏名望 JSON 和 operation 插入故障都验证完整回滚，同 operation 重试成功，重启回放不重复发放；相同 operation 不同输入冲突、另一 operation 重复领奖拒绝。只读子代理 `reputation_gap_audit` 审阅未迁移名望入口并指出 D4/D7 是较小闭合切片；`content_gap_audit` 审阅公共事件合同并比较切片边界，两者均未修改工作树。主线负责共享奖励接入、QQ/OneBot 测试和文档收敛，没有并行改动同一仓储或测试文件，也没有新增运行时版本标识或兼容分支。routine、派遣、试炼塔、共享状态工具和本切片聚焦回归 100 项通过；其余剧情/活动名望写入及灵泉事件完整规则内容化留待后续。

108. **已完成（灵泉事件完整内容与轮次快照）**：灵泉事件的时段、持续时间、准入、贡献来源物品、每份贡献值、个人上限、全服目标、领取门槛、领奖窗口和基础/完成奖励均由 `data/事件/事件.json` 与 `data/奖励/奖励.json` 读取并严格校验。创建轮次时冻结事件名称、说明、来源物品名称、全部规则和奖励快照；查询、探索来源投影、结算和领奖不再读取现行配置。探索结果只在活动窗口内投影，没有来源物品不创建轮次，同一来源 operation 在一轮内唯一，贡献按冻结个人上限封顶；失败轮次只发基础奖励。QQ 官方与 OneBot V11 覆盖新配置轮次、内容改值/关闭后的旧轮次重启领取、时段/目标/门槛/上限/来源物品/每份贡献值、坏配置拒绝、重复来源和探索/图鉴投影回滚。`content_gap_audit` 只读核对事件字段与快照合同，`gather_transaction_reuse` 只读审阅探索事务边界和共享资产入口，`spring_reward_reuse_audit` 只读审阅奖励快照与失败领奖边界；三者均未修改工作树。主线统一实现规则、投影、仓储、应用、内容、玩家文案和双适配器测试，没有并行修改同一仓储或测试夹具，不新增运行时版本标识或旧格式兼容分支。切磋与训练傀儡仍为只读观战，正式 PvE/PvP 结算路径未改写。

109. **已完成（灵泉小径与云舟秘境奖励事务收敛）**：两处秘境在入场时冻结首通/重复奖励、随机资源结果、地方名望键及上限和图鉴分类；结算通过 `utils.player.grant_player_reward` 与装备、背包、地方名望、`codex_entries`、秘境状态及 operation 同事务提交，结果只记录封顶后的实得名望。坏名望 JSON、损坏奖励快照及 operation 插入故障均验证原子回滚和同 operation 重试；配置上限变化后重启仍使用旧快照，QQ 官方与 OneBot V11 均覆盖结算/恢复/重放。真实 PvE 结算未改写，切磋和训练傀儡仍只读观战。本条当时只收敛奖励事务；静态秘境定义随后由第 110 条独立迁移，不能把本条的历史“尚未完成”描述重新作为待办。无运行时版本标识或旧格式兼容分支。
110. **已完成（普通四处秘境定义与所得内容化）**：雾隐秘境、灵泉小径、雾隐洞天二层与云舟秘境现从 `data/冒险/秘境.json` 读取名称、描述、别名、境界、地点、体力/凭证成本、路线、守护敌人、次数、期限、名望地点及首通/再入奖池；规则解析严格校验境界、地点、敌人、物品、图鉴和名望引用。每次入场冻结名称、敌人、路线、首通状态、按运行编号确定性抽取的再入所得、名望上限和图鉴分类；恢复/结算只读快照。重复所得包含明确的无所得结果，成功但无所得仍显示行程完成。奖励、角色资产、地方名望、图鉴、秘境状态和 operation 保持同一事务，正式 PvE 使用既有自动战结算，切磋和训练傀儡仍为只读观战。秘境定义、行程恢复及奖励结算专项测试 37 项通过，含两种适配器的内容变更、引用拒绝、重启恢复、封顶、账本重放、故障回滚和重试。`secret_realm_content_audit` 只读审阅定义缺口、引用闭合、再入奖池消费与快照边界；`reward_write_gap_audit` 只读盘点共享角色奖励入口及相邻声望写入缺口，未修改工作树，其余声望入口留作独立切片。主线负责规则、仓储、用例、JSON、玩家文案、测试与最终收敛；无并行编辑同一仓储或测试，无运行时版本标识或旧格式兼容分支。

加权抽取统一使用 `utils.randomness.deterministic_weighted_choice`，并由内容奖励池和悬赏选择共同复用；秘境、奖励、悬赏、内容/文档及版本字段门槛组合测试 334 项通过，运行时代码与测试 `compileall`、全量内容 JSON 解析及 `git diff --check` 均通过。

111. **已完成（金丹突破地方名望嘉奖内容化）**：金丹突破定义不再保存固定地方名望数量，改为引用 `data/奖励/奖励.json` 的 `reward.breakthrough.golden_core`；该奖励目前只允许青石镇地方名望。开始突破时冻结奖励快照、名望键和地点上限，结算从快照恢复并通过 `utils.player.grant_player_state` 与境界、功勋和 operation 在同一事务提交，结果只记录封顶后的实际所得。奖励内容改值或关闭、地点上限变化、停机重启、坏名望 JSON、奖励写入/账本故障、重复 operation 和不同用户输入冲突均已覆盖；故障解除后原 operation 可重试。QQ 官方与 OneBot V11 的突破入口均通过专项测试，专项 30 项通过；正式 PvE/PvP 结算未改写，切磋和训练傀儡仍是只读观战。`breakthrough_reputation_audit` 只读审阅奖励合同、名望直写和快照缺口；`breakthrough_test_audit` 只读审阅双适配器、封顶、恢复和故障测试缺口；两者均未修改工作树。主线负责模型、规则、仓储、内容、玩家文案、测试、文档和最终验收；没有新增运行时版本标识或旧格式兼容分支，历史未带新快照字段的会话不提供兼容回退。
112. **已完成（道历奖励事务复用）**：功业领取、机缘密令、道契激活/领取和问道行卷奖励统一经 `utils.player.grant_player_reward_actual` 拆分并提交灵石、背包、精力、地方名望和服务信誉；道历规则传入青石镇名望键与当前地点上限，共享入口返回封顶/资源上限后的实际到账，移除原仓储直接改写 `player_reputations.local_json` 的分支。QQ 官方与 OneBot V11 覆盖功业名望封顶、密令组合奖励、精力上限、重启 operation 重放、输入冲突和损坏名望 JSON 的原子回滚；同一 operation 在修复数据后可重试。子代理协作规范已在开发指南保留；本条规模较小，主线未再拆分写入代理，避免并行修改同一仓储和测试夹具。切磋、训练傀儡继续只读观战，正式 PvE/PvP 结算路径未改写；没有新增运行时版本标识或旧格式兼容分支。
113. **已完成（生活域状态变更与快照校验收敛）**：城镇委托交付改用 `utils.player.change_player_state_actual`，由同一状态事务统一处理材料扣除、灵石发放、数值变化、地方名望和服务信誉，并返回封顶后的真实差值；公共项目领奖与短途运输结算同步复用该入口，移除仓储内重复的奖励前后读取。委托准入和交付通过共享名望投影读取，不再直接解析 `local_json`。委托快照解析改为严格对象校验，坏快照在资产、委托状态和 operation 写入前原子拒绝，修复快照后同一 operation 可重试，重启后只回放一次。新增通用状态事务的正负资产、数值与封顶单测，以及 QQ 官方/OneBot V11 坏快照恢复测试。子代理审阅了测试缺口，主线审核并纳入双适配器测试，负责代码、边界和最终验收；没有并行修改同一仓储、运行时版本标识或旧格式兼容分支。稳定键/别名删除后的原文字 operation 重放仍留作后续明确切片。

114. **已完成（角色名望读取投影收敛）**：新增 `utils.player.player_local_reputation(s)`，地方名望与服务信誉读取统一经过严格投影；居所、道统服务派遣、服务订单、虚空塔、三界塔单人/双人准入和战斗快照不再重复查询或解析 `local_json`。角色资料与化神突破移除把地方 JSON 中 `faction.*` 叠加到正式阵营声望的旧分支，只认 `players.faction_reputation_json`。损坏的地方名望 JSON 在扣除体力、租金或创建战斗/试炼局前原子拒绝；QQ 官方与 OneBot V11 的虚空塔入口覆盖坏 JSON、资源不变、修复后同 operation 成功、重复请求和重启重放，工具单测覆盖缺行、默认值和非法 JSON。子代理 `reputation_gap_audit_next` 只读盘点直接读取与旧叠加路径，`reputation_test_audit_next` 只读核对双适配器、恢复、幂等和观战边界；两者均未修改工作树。切磋与训练傀儡仍只读观战，正式 PvE/PvP 结算未改写；不新增运行时版本标识或旧格式兼容分支。

115. **已完成（物品使用历史身份回放）**：物品使用 operation 保存原始请求参数、当时可用的物品引用集合、冻结物品名称和阵法目标名称。重放先读取同一角色的 `items.use` 账本，再解析当前内容；物品改名、删除旧别名或关闭后，原文字请求仍能在重启后返回原结果，使用另一引用会返回输入冲突。恢复资源选项由物品内容声明的 `resources` 驱动，不再在入口重复维护完整选项表；扣背包、数值封顶、冷却和 operation 仍沿用同一角色状态事务。QQ 官方与 OneBot V11 共用 application/repository，正式 PvE/PvP 结算未改写，切磋与训练傀儡仍为只读观战。

本条由主线统一修改物品 application、repository 与测试；`restore_choice_contract_audit` 只读核对内容合同、共享资产事务和历史回放边界，`restore_choice_test_audit` 只读核对双适配器、恢复、幂等和观战测试缺口，两者均未修改工作树。主线补充改名/删除旧别名后的跨重启原文字回放和输入冲突测试，未加入旧格式兼容分支、运行时版本标识或玩家可见开发文案。

116. **已完成（短途运输起运历史身份回放）**：短途运输起运 operation 先在 application/repository 读取账本，再解析当前路线和货物；结果快照保存原始请求参数以及当时路线、货物、灵骑的等价引用形状。路线或货物改名、删除旧别名、关闭后，原文字请求在重启后仍回放原起运结果；同一 operation 换数量或不属于冻结引用的输入返回冲突，隐式货物的请求形状不被显式货物替代。并发落库路径也重新校验快照请求表，损坏的 operation JSON 或缺字段只读拒绝，不扣体力、不扣货、不改变路线。结算继续只读出发快照，并通过共享角色状态事务提交资产、名望、目的地、灵骑和 operation；正式 PvE/PvP 结算未改写，切磋和训练傀儡仍为只读观战。

本条由主线统一修改 `route_use_cases.py`、`route_repository.py` 与运输专项测试；`restore_choice_contract_audit` 只读审阅路线/货物/灵骑引用、内容关闭后的快照边界和并发事务，`restore_choice_test_audit` 只读审阅 QQ 官方/OneBot V11、重启恢复、输入冲突、坏 JSON 和观战/PvE/PvP 边界，二者均未修改工作树。专项运输测试 55 项通过，未引入运行时版本标识、玩家可见开发文案或旧格式兼容分支；服务订单等其他生活域的旧名称/别名回放仍按独立切片处理。

117. **已完成（服务订单发布历史身份回放）**：发布服务 operation 先读取账本，再解析当前服务内容；发布结果保存原始请求参数及发布时的服务键、名称和别名引用。服务改名、删除旧别名或关闭后，QQ 官方与 OneBot V11 在重启后仍可用原文字请求返回原订单，换用未保存的服务或报酬输入返回冲突；请求形状、引用集合、状态、时间和交付物校验失败时只读拒绝，不重复扣除灵石或创建订单。发布、接取、取消和结算继续共享同一 application/repository，订单快照与资产变更保持原事务边界；正式 PvE/PvP 结算未改写，切磋和训练傀儡仍只读观战。

本条采用主线统一实现。`service_audit_now` 只读核对内容合同、快照、共享状态事务和直接入口风险；`service_test_audit_now` 只读核对 QQ 官方/OneBot V11、重启、幂等、冲突、坏账本和观战/PvP 边界；两者均未修改工作树，结论已由主线纳入实现与测试。服务订单专项 16 项通过；未新增运行时版本标识、玩家可见开发文案或旧格式兼容分支。

118. **已完成（城镇委托接取与交付历史身份回放）**：接取与交付在 application/repository 先按 operation 读取账本，再解析当前委托内容；结果快照保存原始请求形状、委托稳定键、名称与别名引用，接取快照同时冻结交付所需的委托身份。委托改名、删除旧别名或关闭后，QQ 官方与 OneBot V11 在重启后仍可用原文字请求重放；换用另一委托、显式与隐式交付形状不一致或不属于冻结引用的选择器返回冲突。operation JSON、字段、请求引用、奖励结果、时间与 request hash 校验失败时只读拒绝，不扣物品、不发灵石、不改名望/信誉、不改变 claim 状态；修复账本后同一 operation 可重试。正式 PvE/PvP 结算未改写，切磋与训练傀儡仍只读观战。

本条采用主线统一修改 `commission_repository.py`、`use_cases.py` 与委托专项测试。子代理 `next_vertical_audit` 只读核对接取/交付入口、适配器归一化、快照与观战边界，给出 operation-first 和双适配器测试建议；`next_reward_gap_audit` 只读核对共享角色状态事务、资产回滚和坏快照缺口；两者均未修改工作树。主线负责实现、结果文案、QQ 官方/OneBot V11 重启回放、输入冲突、坏账本修复重试及最终验收；未增加运行时版本标识、玩家可见开发文案或旧格式兼容分支。

## 7. 执行记录（文档基线）

### P0：已完成（文档与内容裁决）

已完成：

- 建立新游戏总纲、基础/玩法/扩展分册索引、上游参考边界和 v0.1-v0.6 内容包阅读顺序。
- 固定三层世界：玄天界为主大世界，魔界/妖界为半大世界，洞天/福地为遍布三界的小世界。
- 固定公共境界与六大道途：体修、法修、器修、魔修、妖修、辅修；炼丹、炼器、布阵为辅修主类。
- 新增角色域 v0.1 内容权威，固定 `new_user -> mortal -> seeker -> cultivator`、资质范围/总和、初始奖励、引导、入道、稳定键、幂等和回滚。
- 固定 P0-P8 新玩法交付顺序、每阶段验收与回滚点，明确不从旧项目继承玩法数值、命令、物品、表结构或业务流程。
- 为全部 121 份 `content-v0.1.md` 至 `content-v0.6.md` 补齐版本、稳定键、前置、成本、产出、随机/快照、失败、幂等、权限、观测、关闭和回滚合同；发布校验入口统一记录在内容域文档中，不依赖已移除的脚本目录。
- 修复跨域内容合同：技能命名统一为 `skill.<path>.<name>`，配方输出均有 `item.*` 定义，金丹/元婴/化神/炼虚/合道前置任务和终局资源路径均有稳定键定义，v0.1 占位境界不再被当成开放内容。当前玩家端任务可达性以[当前开发状态](current-status.md)为准。
- 改为每境十层：L1–L3 入门、L4–L6 稳固、L7–L9 圆满、L10 混元；`realm_layer` 取代旧三段阶段字段，跨境只允许 L10，旧三段数据必须显式迁移或审核。
- 移除娱乐、媒体、WebDAV、第三方账号、小游戏与娱乐积分的全部产品文档/内容包；新增常驻经营域的 v0.1-v0.6 内容包，提供从凡人起的居所、灵田、委托、服务、商路和公共建设循环，且禁止直接产修为/突破准备度。
- 按修仙文游风格新增用户提出的系统：道历问安/补录、灵木聚财、日/周/月道契、机缘寻宝、问道行卷、道号、功业录、七日入道、斗法留影、悬赏榜、秘境试炼、主线道途、闭关修行、道脉天书、体质根性、灵兽/灵骑、神通参悟、法器祭炼/灵纹重铸和机缘密令；每项都有稳定键和版本内容。

文档验收结果：

- JSON 内容包格式校验、`pytest -q` 和 `git diff --check` 通过；内容引用闭合、发布边界、任务/终局可达性和十层规则以[完整内容开发总表](content-development.md)及人工评审为准。
- 本地 Markdown 链接检查：192 份文档全部通过。
- `git diff --check`：通过。

### 工程状态：P3、P4 与 P5 最小切片历史记录

本段记录当时 P3-P5 的验收基线，不表示当前分支的测试数量或开放边界。当前验证使用
[`docs/testing.md`](testing.md) 中的命令，当前运行时状态统一以
[当前开发状态](current-status.md) 为准。当时 P3 写入口均使用事务和 operation ledger，展示层只显示中文阶段、境界、地点、资质和道号，不泄露平台用户 ID
或内部稳定键。P4/P5 当时开放感气调息、灵泉谷修炼、基础/静养闭关、最小居所、资源恢复、
聚气/筑基突破、首版个人生产、四种探索模式、草药/生产悬赏、当前首要道途的道脉天书和低阶法器养成；
金丹以上突破、秘境/遗府和战斗当时仍未开放；生产委托、固定摆摊和灵泉世界事件已完成跨适配器闭环；
该历史记录中的“神通参悟只保存构筑快照”已由 v0.3 战斗扩展更新，当前技能会进入自动战斗快照；灵兽已接入结缘、蜕变和运输生命周期首条运行时切片，运输险象会按冻结种子进入受伤休养。
### 2026-09 三界贸易口切片更新

`beast.three_realms_trade_port` 已注册为从万兽山出发的元婴 L1 地点，`trade.three_realms` 已开放魔核 2、妖血 2 兑换绑定神魂晶 1，每角色每周 3 次；贸易事务再次校验魔界与妖界声望均为 200，并已完成 QQ 官方与 OneBot V11 验收。`quest.beast_intro` 已通过妖界史阅读、本人近郊结算证据和一次性提交事务接入；正式引导资格只替代万兽山 200 声望门槛，不替代元婴要求。限量拍卖和其他跨界配方仍未开放。

`auction.weekly.<week_id>` 已开放独立拍卖事务：每周 20 槽，非绑定物品发布，+5% 递增竞价、被超越退款、成交/流拍及 10 分钟恢复窗口；双适配器路径见 `test/test_auction_v03.py`。复杂市场玩法、批量委托和跨服交易仍未开放。

`market.purchase_order` 已开放跨界求购事务：每角色 3 单、12 小时有效期、800 bp 买方托管，发布时冻结买方阵营/地点/盟约快照；卖方匹配时记录阵营与物品区域来源并锁定非绑定物品，10 分钟交付窗口超时释放物品，订单过期原路返还灵石；双适配器路径见 `test/test_purchase_order_v03.py`。复杂批量委托、跨服市场和 Web 写操作仍未开放。

### 2026-10 天劫试炼内容化切片

本条切片把 `event.heaven_tribulation` 的试炼顺序、展示、门槛、成本、奖励、债务、冷却、随机池和时长收敛到事件内容。规则解释器严格校验事件字段、试炼顺序、奖励物品引用、选择条件和类型；仓储在正式 PvE 自动战开始前冻结完整定义，结算、失败冷却和重启恢复只读取会话快照。新会话读取当前内容，已开始会话不受内容改动影响；重复 `operation_id` 返回原结果，不重新抽取或重复发放。QQ 官方与 OneBot V11 共用同一 application/repository，新增临时内容变更、严格引用拒绝和快照恢复测试；切磋与训练傀儡仍不创建邀请、不扣资产、不发奖励、不写图鉴。

本条采用主线实现，未并行修改仓储或夹具；开发协作遵循 `docs/development-guide.md` 的子代理约定。后续若拆分审阅任务，子代理只读核对内容合同、共享工具复用、适配器边界和恢复风险，文件所有权与结论必须先记录，再由主线统一合并和验收。

### 服务订单内容化与结算事务收敛

本条将 `data/生活/生活.json` 的服务记录作为服务订单唯一内容来源，规则解析名称、别名、说明、准入、成本、报酬范围、交付物、失败返还、地点要求、每日次数和期限，并严格校验物品引用。发布时扣除并锁定委托人报酬，订单保存完整业务快照；接取、成功/失败/过期结算和重放只读取快照，资产与玩家数值统一走 `utils.player` 共享状态事务。过期接取在同一事务退回报酬并记入 operation；损坏快照和各写入阶段故障原子回滚，恢复后可用原 operation 重试，未加入旧格式兼容分支。

本条由主线统一修改服务规则、仓储、用例、内容和测试，未让多个代理并行编辑同一模块。可复用的子代理只承担只读审阅：内容引用闭合、共享资产/玩家状态入口、双适配器路径、正式 PvE/PvP 与只读观战边界、恢复和测试缺口；审阅结果须带文件与事务边界，再由主线合并并重新验收。专项测试覆盖内容改值后的历史快照、坏快照、过期退款 operation、故障回滚重试、重启恢复和 QQ/OneBot V11 真实事件；玩家可见文案保持修仙文游语气，不出现开发状态或版本标识。

### 装备独立穿脱槽位

本条开放 `我的装备`、`穿戴装备`、`卸下装备`。`equipment_instances` 保存 `equipped` 状态，法器、防具、饰品分别占用独立槽位；穿戴事务校验道途、境界、耐久、长行动互斥和槽位占用，并在同一事务写入装备状态、`equipment_loadout_events` 与 operation ledger。装备实例创建时空槽首件自动穿戴，后续同槽实例收纳；正式单人/队伍 PvE、天劫、终局与竞技场共享已穿戴且有耐久的快照读取，已开始的战斗仍使用开战快照。切磋与训练傀儡保持只读，不创建穿脱流水、不改变装备状态、不扣资源、不发奖励、不写图鉴。

本条使用两个只读子代理：`equipment_slot_contract_audit` 核对装备内容合同、槽位约束、快照和事务边界；`equipment_slot_test_audit` 核对装备、正式 PvE/PvP、观战和双适配器测试缺口。子代理未修改工作树，主线统一实现 repository/application、共享装备快照工具、两条适配器测试和文档。专项覆盖 QQ 官方与 OneBot V11、同槽冲突、幂等重放、输入冲突、重启恢复、只读装备查看和正式战斗快照；没有新增运行时版本标识，也没有加入旧格式兼容分支。

### 物品内容合同与使用事务收敛

本条把 `item` 内容记录作为名称、别名、物品类型、绑定方式、交易属性和效果的唯一运行时来源。新增共享内容解析入口后，成品使用、固定价格摆摊、拍卖和求购均按当前 `ContentBundle` 校验并展示；经济域不再维护物品名称、别名或不可交易稳定键清单。云灵茶的待修炼效果改为通用待消费快照，保存效果类型、数值、来源 operation 和消费时间，在修炼开始时冻结并消费；迷雾屏障的目标地点也由物品效果内容声明，地点别名从地点记录读取。玩家可见冲突文案使用修仙文游表达，不展示请求编号。

本条主线负责修改物品规则、内容解析、物品/经济仓储、修炼快照和双适配器测试；未让多个代理并行编辑同一仓储或测试夹具。允许合理使用子代理的约定继续保留：本条只读审计范围为内容合同、共享资产/玩家状态复用、正式 PvE/PvP 与切磋/训练只读边界、适配器入口、恢复和测试缺口；子代理不得自行加入运行时版本标识、玩家可见开发文案或旧格式兼容分支，结论带文件、函数和事务边界后由主线统一合并。专项覆盖临时内容改名/别名、坏内容引用、双适配器使用、同 operation 重放与输入冲突、背包原子扣除、修炼重启恢复和市场交易边界；正式 PvE/PvP 继续按既有结算，切磋与训练傀儡未接入物品写事务。

### 灵食择一恢复与冷却事务

本条把 `restore_choice` 作为物品效果的通用执行器：灵食内容声明可恢复的体力/精力、恢复量和冷却，
使用者明确选择一项，`utils.player.change_player_state_actual` 与 `utils.assets` 在同一事务中完成背包扣除、
数值封顶和实际所得记录，冷却表与 operation 一并落盘。重放只回放原结果；同一操作改换资源会被拒绝，
冷却期间不再扣物品，数据库写入故障回滚后原操作可重试，重启仍保留冷却。玩家回复只写修仙文游语气，
不出现版本、内部编号或存储实现；正式 PvE/PvP 继续正常结算，切磋与训练傀儡不进入该写事务。

本条由主线统一修改物品规则、仓储、schema、玩家文案与测试。`next_slice_audit` 仅只读核对共享资产/数值
入口、内容变更、恢复和观战边界，未修改工作树；主线负责汇合并避免同一仓储或测试夹具的并行写入。专项覆盖
QQ 官方与 OneBot V11、内容改量、上限封顶、冷却跨重启、operation 重放/冲突、操作写入故障回滚与重试。

### 修炼方式参数内容化

本条将四种修炼方式的名称、别名、成本、时长、基础修为、环境倍率、次数、境界/地点门槛、独处条件和神魂参数收敛到 `data/养成/修炼.json`，规则层只负责严格校验和解释。开始事务先按 operation 账本回放，再解析当前请求；新会话保存名称、时长、成本、收益、状态倍率和神魂上限快照，结算、过期恢复、取消和重启均不重新读取当前内容。关闭方式只阻止新会话，历史会话仍按快照完成；坏 JSON、重复名称/别名和断裂引用在扣除资源前拒绝。

本条合理使用两个只读子代理：`cultivation_contract_audit` 审阅内容字段、历史快照和关闭语义，`cultivation_test_audit` 审阅 operation、恢复、故障回滚、双适配器及正式 PvE/PvP/只读观战边界；子代理不直接修改仓储或测试夹具，主线统一实现、处理边界并完成最终验收。专项覆盖 QQ 官方与 OneBot V11、参数改值、改名删别名后的重启回放、坏账本只读失败、内容校验和资源原子性；不新增运行时版本标识或旧格式兼容分支。

### 内容字段与固定指令文案分流

本轮复核发现修炼方式的四条 `desc` 只用于固定指令引导，既不参与规则判断，也不进入会话快照；已移出
`data/养成/修炼.json`，由修炼域代码维护。悬赏令、剧情、秘境等随记录、境界、路线或随机结果变化的
玩家文案仍保留在内容包，并继续随业务快照冻结。内容合同新增判断标准：固定命令格式、错误提示、
通用确认语和少量固定引导短句不配置化；只有需要随内容包调整或随历史结果回放的文案才登记字段。
本轮采用主线修改规则、数据、测试和文档；`cultivation_contract_audit` 与 `cultivation_test_audit`
仅提供只读审阅，结论已合并。未引入运行时版本标识、玩家可见开发文案或旧格式兼容分支。

### 开发顺序复盘与领域去重规则

此前实施记录按历史完成时间累积，不能直接作为下一条开发顺序；同一领域曾因共享状态、内容化和
历史回放分别被触碰，容易让“补缺陷”和“重复重构”混在一起。本轮起按当前状态页缺口、代码/测试
实际闭合度、最近领域提交和可回滚边界选唯一垂直切片；已标记 `open` 且验收闭合的领域只允许修复
明确缺陷，不再重复设计。开始切片前先登记领域、入口、文件所有权、排除范围和验收；子代理按该登记
只读审阅或在不重叠的文件边界编码，主线统一合并。若状态页与实施记录冲突，先修正文档再开发，
不得把历史“仍待”描述重新当作任务。

### 宗门申请生命周期与恢复闭合

本条只处理宗门成员生命周期中尚未实现的申请人撤回：新增 `撤回入宗申请` 入口，限定为申请人自己的
`pending` 申请，撤回写入独立 operation，申请状态变为 `withdrawn`，不改变成员、冷却或任何资产。
申请、撤回、审批和离宗均先回放 operation，再进入当前状态校验；损坏的结果账本只读拒绝，写入故障由
SQLite 事务整体回滚，修复后原 operation 可重试。审批结果快照补齐实际审核人的角色标识。

入口与主线文件：`xiuxian/social/sect_repository.py`、`sect_use_cases.py`、`xiuxian/application.py`、
`adapters/base.py` 及宗门专项测试。QQ 官方与 OneBot V11 共用同一 application/repository；重启只依赖
持久化状态，不新增运行时版本标识，也不保留旧格式兼容分支。宗门战、宗门仓库、生产联盟、队伍和正式
PvE/PvP 结算不在本条范围，切磋与训练傀儡仍保持只读观战。

本条采用主线统一修改共享宗门仓储、应用和测试夹具。`adapter_gap_audit` 只读核对宗门双适配器覆盖、
审核人快照和损坏账本风险；`next_slice_audit` 只读盘点相邻世界切片，确认不与本条重叠；两者均未修改
工作树。主线负责汇合结论、补齐 QQ/OneBot 申请→撤回/审批→离宗流程、跨重启回放、输入冲突、坏账本
拒绝、故障回滚与修复重试，并更新当前状态和社交合同。剩余缺口是宗门创建/人数/费用等规则仍由社交域
合同常量提供，另行登记内容化切片，不在本条顺手迁移。

### 云舟魔界/妖界引导内容化与共享事务

本条只处理云舟抵达后的魔界引导、妖界史阅读与妖界引导完成。`data/任务/任务.json` 声明两条引导的
地点、境界、航线、证据、成本、入口旗标和奖励引用；`data/奖励/奖励.json` 声明固定奖励。规则层严格
校验内容引用，仓储在同一事务中先回放 operation，再读取当前内容；新请求冻结成本、奖励和任务快照，
扣费后重新读取玩家行再发放奖励。历史 operation 只依赖自身快照，内容改值、关闭或重启不改变已完成结果。

入口与主线文件：`xiuxian/world/cloud_rules.py`、`cloud_repository.py`、`world/use_cases.py`、共享
`utils/operations.py`、`persistence/errors.py`、任务/奖励内容及世界引导专项测试。共享资产、玩家数值、
声望事务继续由 `utils.player` 提供；云舟正式抵达仍按既有移动快照结算。切磋与训练傀儡不创建邀请、
不扣资产、不发奖励、不写图鉴，正式 PvE/PvP 结算不在本条范围。

本条由主线统一修改仓储、规则、内容、玩家文案和测试夹具，未让多个代理并行编辑同一文件。
`cloud_contract_audit_next` 只读核对任务/奖励引用、地点境界和证据合同；`cloud_test_audit_next` 只读
核对 QQ 官方、OneBot V11、重启、恢复、坏账本、写入故障和跨用户证据归属；两者均未修改工作树。
专项验收覆盖内容改值后的历史回放、损坏奖励快照、operation 写入故障回滚与原 operation 重试、两种
适配器和玩家证据隔离。运行时不保存内容/规则版本标识，也不保留旧格式兼容分支。

其他世界剧情与活动的声望写入继续按单独垂直切片迁移，不能把本条已闭合的引导流程重新设计。

### 云舟与妖界引导损坏账本恢复夹具

本条已完成，范围只收口上一条云舟切片的恢复缺口，不重新设计云舟航线、任务规则或奖励事务。专项夹具
分别对 `world.recover_cloud_boat`、`world.accept_demon_intro`、`world.read_beast_history` 和
`world.complete_beast_intro` 的成功 operation 结果写入损坏 JSON；重启后原请求必须只读失败且不改变
位置、灵石、体力、声望、入口旗标或任务事件。修复原账本后，原 operation 必须在 QQ 官方和 OneBot V11
两条适配器路径稳定重放，并保持单次结算。

本条由主线直接修改 `test/test_world_cloud_routes.py`、`test/test_beast_intro.py` 及本计划，未启用子代理：
改动仅是两个既有专项夹具的独立恢复断言，不涉及共享仓储或测试夹具的并行所有权。`operation_replay` 的
严格拒绝逻辑沿用共享工具，未新增运行时版本标识、玩家可见开发文案或旧格式兼容分支。其他世界剧情和
活动的声望写入仍按独立垂直切片登记。

### 道历问安与补录奖励内容化

本条只处理 `道历问安` 与 `补录道历` 的奖励来源。当前两条路径仍由
`xiuxian/routine/rules.py` 内置灵石、精力和连续七日机缘签数值，违反奖励内容唯一来源合同；灵木、
功业、道契、机缘寻宝、问道行卷和七日目标已闭合的奖励不在本条重新设计。新增
`reward.routine.checkin.daily`、`reward.routine.checkin.streak` 与 `reward.routine.makeup.daily`
固定奖励记录，规则层通过共享 `reward_definition` 严格解析，问安/补录事务继续使用现有角色状态
写入口，并把实际到账结果写入 operation 和业务记录快照。新请求读取当前内容，已完成 operation
只回放原快照；内容改值、关闭、重启、输入冲突和坏内容均不得造成重复扣发或半笔奖励。

入口与主线文件：`data/奖励/奖励.json`、`routine/rules.py`、`routine/repository.py`、道历专项测试及
本文件/当前状态。主线代理负责内容、解析、事务接线、玩家文案与最终验收；`routine_contract_audit`
只读核对字段、共享奖励事务和快照边界；`routine_test_audit` 只读核对 QQ 官方、OneBot V11、
重启、operation 幂等/冲突、坏内容与故障回滚。两个子代理不修改仓储或测试夹具，其他已闭合 routine
能力冻结，不新增运行时版本标识或旧格式兼容分支。切磋与训练傀儡仍为只读观战，正式 PvE/PvP 结算
不在本条范围。

### 虚空档案奖励与周任务内容化

本条切换到尚未闭合的事件域，只处理已开放的 `event.archive_unlock` 链：档案守卫首通/重复所得、
三项档案碎片周任务目标与物品奖励、每项功勋和三项完成后的解锁功勋迁入事件与奖励内容。档案航道、
守卫自动战、主线、道源门资格和档案图鉴不重新设计；切磋与训练傀儡仍为只读观战，正式 PvE/PvP
结算不在本条范围。

入口与主线文件限定为 `data/事件/事件.json`、`data/奖励/奖励.json`、`data/道具/材料.json`、
`nonebot_plugin_xiuxian_3/xiuxian/events/void_archive_rules.py`、`void_archive_repository.py`、
`void_archive_use_cases.py`、生产物品展示标签及档案专项测试。规则层只解析当前内容并返回冻结的奖励/任务快照，仓储继续
沿用现有事务、operation 账本和共享角色状态入口；历史 operation 只回放快照，内容关闭或改值只影响
新周次/新结算。

主线代理负责 JSON、规则、仓储、玩家文案和最终验收；`void_archive_contract_audit` 只读核对事件/奖励
引用、任务证据与快照边界，不修改工作树。验收必须覆盖 QQ 官方与 OneBot V11、内容改值、跨重启回放、
坏内容原子拒绝、operation 冲突/写入故障重试及首通/重复奖励；不新增运行时版本标识或旧格式兼容分支。
本条已完成：档案奖励、任务目标、任务名称和解锁时长均由内容包消费，首通/重复奖励与任务/解锁奖励通过共享角色状态事务提交，运行与任务记录保存完整奖励快照；生产物品展示优先读取统一物品内容，移除档案碎片的第二份开发标签；历史 operation、已领取任务和任务展示在内容改动及重启后保持原结果。专项测试覆盖 QQ 官方与 OneBot V11 的适配器注册路径、幂等与冲突、内容改动回放、坏字段/坏奖励引用拒绝；`compileall`、全部 JSON 解析和 `git diff --check` 已通过。

### 雾隐试炼塔规则与奖励内容化

本条已完成。范围限定为已开放的 `tower.mist_trial`：楼层上限、境界/层数门槛、体力、日次数、敌人分段、首通/重复奖励和特殊楼层奖励已迁入 `data/特殊/试炼塔.json`；固定命令格式、错误提示和通用确认语仍由特色玩法代码维护。开始挑战时冻结楼层定义、敌人、体力、奖励、名望上限和图鉴入口，战斗结算、领奖、重启回放和内容关闭只读取该快照；新挑战在内容关闭后拒绝创建，不改变试炼塔状态机、自动回合引擎、正式 PvE 结算或切磋/训练傀儡只读边界。

入口与主线文件限定为 `data/特殊/试炼塔.json`、`data/内容清单.json`、`data/战斗/敌人.json`、`data/道具/材料.json`、
`xiuxian/combat/rules.py`、`xiuxian/specials/tower_rules.py`、`tower_repository.py`、`tower_models.py`、`tower_migration.py`、
`tower_use_cases.py`、试炼塔专项测试及特色玩法文档。规则解析严格校验境界、敌人、物品、图鉴和地方名望引用；坏内容在扣体力前拒绝。
奖励、背包、地方名望、图鉴和塔局状态沿用共享角色状态事务。主线统一修改内容、规则、仓储、玩家展示和测试；子代理只读审计内容引用、
共享奖励事务、operation/重启恢复、QQ/OneBot 双适配器及正式 PvE/观战边界，不并行修改同一仓储或测试夹具。

验收覆盖 QQ 官方与 OneBot V11、内容改值对新旧挑战的影响、关闭新挑战而不影响历史领奖、坏引用原子拒绝、首通/重复奖励、operation 冲突与重放、
战斗启动故障回滚、重启恢复、`test/test_tower.py` 与 `test/test_tower_content.py` 共 12 项、`compileall`、全部内容 JSON 解析和 `git diff --check`。
运行时不保存版本标识，不加入玩家可见开发文案或旧格式兼容分支；切磋和训练傀儡仍为只读观战，正式 PvE/PvP 结算不在本条重写。

### 派遣任务内容化与奖励事务收敛

本条只处理特色玩法域中尚未闭合的派遣任务：六条派遣的名称、说明、别名、耗时、次数、成本、准入、
风险权重、失败返还、可变数量奖励和地方名望引用统一登记在 `data/生活/生活.json`；运行时规则只解析
当前内容，不再维护 `DISPATCHES` 业务数值表、按任务键分支或固定名望上限。修炼等只有几句固定引导的
指令文案仍由用例代码维护，不为了“内容化”把短句搬进 data。

入口与主线文件限定为 `data/生活/生活.json`、`data/地图/地点.json`、
`xiuxian/specials/dispatch_rules.py`、`dispatch_repository.py`、`dispatch_use_cases.py`、
悬赏引用校验及派遣专项测试。接受时冻结风险、奖励、地方名望上限和原始成本；结算、失败返还、
图鉴投影、活动来源和 operation 回放只读冻结快照。内容改值或关闭只影响新派遣，历史派遣仍可恢复；
损坏账本、写入故障和输入冲突必须原子拒绝或沿原 operation 重试。派遣奖励继续通过共享角色资产、
数值和地方名望事务提交，QQ 官方与 OneBot V11 共用同一 application/repository。玩家回复使用修仙
文游名称和实际所得，不展示稳定键、任务编号或内部结果枚举；切磋与训练傀儡仍只读观战，正式 PvE/PvP
结算不在本条改写。

本条主线代理统一修改内容、规则、仓储、文案和测试；子代理只做只读合同、事务复用和双适配器审阅，
不得并行编辑同一仓储或测试夹具。项目未正式发布，合同变化直接重构，不保留旧格式兼容分支，也不新增
运行时版本标识。验收覆盖内容改值/关闭、可变数量与风险种子、operation 幂等/冲突、重启恢复、坏 JSON、
事务故障回滚与修复重试、失败返还以及两种真实适配器路径。

### 公开结局图鉴投影

本条只收口终局已有的两条真实结局记录，不扩展道统服务见闻。飞升与留界结局分别登记
`codex.ending.public_ascend`、`codex.ending.public_remain`；结局确认、角色终局状态、终局记录、图鉴发现和
`operation_id` 在同一事务提交。图鉴发现保存首次展示名，内容改名或关闭后，已成功 operation 的重启回放和
图鉴查询仍显示原名；关闭条目不允许新的结局确认。切磋与训练傀儡没有任何关联，正式终局 PVE 结算保持原路径。

入口与主线文件限定为 `data/图鉴/条目.json`、`specials/codex_projection.py`、`specials/codex_repository.py`、
`progression/endgame_rules.py`、`progression/endgame_repository.py`、终局专项测试及本文件/当前状态。主线统一
修改终局事务和图鉴投影；未启用子代理，原因是范围只涉及一个已有事务边界，拆分会让同一仓储产生重叠所有权。
验收覆盖 QQ 官方与 OneBot V11、同 operation 重放/输入冲突、内容改名与关闭后的重启回放、图鉴写入故障原子
回滚和原 operation 修复重试。除本计划后续公共建设投影外，道统服务其余四条见闻仍没有稳定来源和奖励合同，明确留在后续合同闭合切片，
不在本条补造条目或生产者；不新增运行时版本标识或旧格式兼容分支。

### 公共建设道统服务见闻投影

本条承接已有公共建设结算，只增加一个真实来源的图鉴投影，不重写公共项目状态机，也不提前补齐其余
没有生产者的道统服务见闻。六类公共项目在 `data/生活/生活.json` 声明统一的
`codex.dao.service_public_works`；项目按周物化时冻结图鉴稳定键和展示名，达标结算时在原奖励事务内
收入 `service` 类图鉴。项目奖励、物品、灵石、地方名望、图鉴和 operation 必须同事务提交；图鉴写入故障
整体回滚，修复后可沿原 operation 重试。历史项目和 operation 重放只读快照，内容改名或关闭不影响已物化项目，
新项目仍须通过当前内容引用校验。

入口与主线文件限定为 `data/图鉴/条目.json`、`data/生活/生活.json`、
`xiuxian/livelihood/rules.py`、`project_repository.py`、公共项目内容/来源/适配器专项测试及本文件/当前状态。
玩家回复继续使用修仙文游文案，不展示稳定键、operation 或内部状态；训练傀儡与切磋只读观战，不贡献项目、
不扣资源、不发奖励、不写图鉴，正式 PvE/PvP 结算不在本条改写。

本条主线代理直接修改内容、规则、仓储、文档和测试；未启用子代理，原因是投影必须和已有公共项目奖励事务
共享同一仓储边界，并行编辑会产生重叠所有权。验收覆盖 QQ 官方与 OneBot V11、内容改名/关闭后的重启回放、
未知图鉴引用拒绝、operation 幂等与冲突、图鉴写入故障回滚及原 operation 修复重试。项目未正式发布，
合同变化直接重构，不保留旧格式兼容分支，不新增运行时版本标识。

### 道源主线剧情内容化

本条选择依据是当前状态页的开放缺口和可验收入口，而不是沿目录或方案快照顺序重复开发。玄天、领域前线、
虚空档案等主线已有内容解析；盘点发现 `story.mainline.dao_echoes` 仍在 Python 保留三线三十关的剧情表，
因此本条只收口同一冒险域的内容边界，不重写已经闭合的资产事务、正式 PvE/PvP 结算或观战流。

入口为 `道源主线`、`开始道源主线`、`领取道源主线奖励`，文件边界为
`data/剧情/主线.json`、`data/图鉴/条目.json`、主线规则解析、道源仓储/用例和道源专项测试。
路线展示名、关卡名、叙事、炼虚 L10 门槛、路线内前置和三十个图鉴引用由 JSON 提供；规则层复用主线
`ContentBundle` 解析并校验三路线各十关、稳定键连续、路线名一致、图鉴引用闭合和无重复奖励。开始事务
冻结路线展示、关卡名/叙事和图鉴键，领取、重启、operation 回放只读快照；内容改名或关停只影响新开，
已开始关卡仍可领取。首通仍只写故事事件和图鉴，不扣资源、不发资产、不改道途/结局；正式战斗和切磋、
训练傀儡边界均不在本条改动。

主线代理直接修改上述内容、规则、仓储、用例、文档和测试；本条未使用子代理，因为内容解析和快照字段
必须与同一道源仓储保持单一所有权，拆分会产生重叠编辑。验收覆盖 QQ 官方与 OneBot V11、内容变更与
关闭、坏章节结构、重启快照、operation 幂等/冲突及无资产副作用；不新增运行时版本标识，不保留旧格式
兼容分支。剩余缺口：其他仍为 `partial`/`contract` 的剧情与事件按同样盘点原则另行选择，不把未闭合的
道统服务见闻凭空补成来源。

### 战斗敌人内容化与普通多人 PVE 边界收敛

本条根据当前状态页和领域代码盘点选择，不按实施计划行号回到冒险域重复开发。普通 4–5 人队伍 PVE
已有真实入口、持久化、自动回合和双适配器测试，但 `combat/party_rules.py` 仍维护地点到敌人的
Python 映射，`PARTY_BATTLE_REWARD` 仍是第二套奖励来源；战斗域 README 也把已开放的普通队伍写成未开放。
本条只收口两个既有地点的内容边界，不新增副本地点，不重写跨界秘境、正式 PvP、切磋观战或训练傀儡。

入口和文件边界限定为 `data/战斗/敌人.json`、战斗敌人解析、`combat/party_rules.py`、
`combat/party_repository.py`、普通多人 PVE 专项测试，以及战斗域 README、用例、内容合同和当前状态页。
木鼠和雾隐守卫记录补充 `combat_profile.party_profile`，声明普通队伍类型和每名成员奖励；开始时由当前
内容按地点解析唯一敌人，敌人属性、随机池和奖励写入队伍战斗快照，结算、重启和 operation 重放只读快照。
坏内容、重复地点配置和缺失奖励在扣除体力或创建会话前拒绝；内容改值只影响新战斗。

主线代理统一修改内容、规则、仓储、文档和测试；本条未并行编辑同一仓储或测试夹具。允许的子代理职责仅为
只读核对战斗内容合同、共享玩家奖励事务、正式 PvE/PvP 与切磋/训练只读边界、恢复和双适配器缺口；本轮未启用
子代理，原因是范围集中在同一战斗仓储的快照字段，拆分会造成重叠所有权。验收覆盖 QQ 官方与 OneBot V11、
内容改值、坏内容原子拒绝、开战快照、重启回放、operation 幂等/冲突和每名成员奖励唯一性。
不新增运行时版本标识、玩家可见开发文案或旧格式兼容分支；下一条切片不得重新设计本条已闭合的普通 PVE。

### 居所与灵田内容化、快照和恢复闭合

本条不是按实施计划的章节顺序挑选，而是依据 `current-status.md` 的实际缺口、内容合同、真实入口/事务/测试闭合度和最近提交边界，选择生活域中仍未闭合的最小纵向切片。此前生活域的共享奖励事务、委托、运输、服务订单和公共项目分别属于已完成切片；本条不重新设计这些边界，也不把修炼等只有几句固定引导的文案搬进数据文件。

文件所有权限定为 `data/生活/生活.json`、`xiuxian/livelihood/rules.py`、`models.py`、`repository.py`、`field_repository.py`、`use_cases.py`、`xiuxian/utils/randomness.py`、居所/灵田专项测试和本计划/当前状态/内容合同。居所与作物的租金、租期、阶段/名望门槛、灵田容量、种子、成长、维护、收获、随机池、每日次数和名望奖励由 JSON 严格解析，移除 Python 数值表与旧标签表；租赁/播种冻结名称、参数、门槛、随机结果和引用，查询、维护、收获和 operation 回放只读冻结快照。账本回放先校验原始请求再解析当前内容，内容改名、删除别名或关闭不得改变已完成结果；损坏快照或账本只读拒绝，不用默认字段伪造旧格式。

主线统一修改上述文件和测试；子代理只承担只读的合同、事务复用、适配器和恢复审阅，不编辑同一仓储或测试夹具。已完成的共享资产/数值事务、委托/运输/服务/公共项目、正式 PvE/PvP 结算以及切磋/训练傀儡只读观战边界均明确排除。验收包括临时 JSON 改租金/租期/容量/成长/维护/收获/名望、改名/删别名/关闭后的跨重启原 operation 回放、随机结果冻结、坏快照/坏账本拒绝、恢复后结算和既有 QQ 官方/OneBot V11 入口；不新增运行时版本标识、玩家可见开发文案或旧格式兼容分支。

本条闭合后才从当前状态页重新盘点下一条唯一缺口；任何后续修改生活域必须在计划中登记“包含文件、排除文件、验收命令和不再触碰的已完成边界”，避免同一子插件在不同切片中重复重构。

### 已闭合切片：道统回响机缘池

本条按当前状态页登记的开放缺口推进，不按历史内容快照的行号顺序重复修改 routine。入口为
`机缘寻宝 道统回响 [单抽|十连]`；基础机缘池与道统回响共用一套 JSON 奖池解析、确定性抽取、保底和
角色状态事务。准入由内容声明为合道 L1；服务信誉资格尚无独立稳定键，待合同闭合后再接入；资质与
引导 JSON 不承载服务资格。单抽/十连成本、票券、奖项、展示名和保底均随池记录读取，抽取快照保存真实
业务输入和结果，不保存运行时版本标识。

道统回响只允许新篇章线索、展示性物品和道统服务名望，严格拒绝道果、天劫凭证、飞升功勋、飞升凭证、
修为和战斗属性。operation 先于现行内容与资格解析回放；内容改值、改名或关闭只影响新请求，损坏内容、
坏快照、账本冲突和事务故障都不得留下半笔资产。主线负责上述内容、规则、仓储、用例、表结构和专项测试；
子代理只承担合同、恢复或适配器只读审阅，不编辑同一仓储与测试夹具。明确排除道统主线、派遣、生活域
共享状态、正式 PvP/PvE 和切磋/训练傀儡观战。

本条已闭合并进入冷却。后续切片必须重新盘点状态页和最近提交，不能因为 routine 仍有历史待办就重复改造
机缘仓储；只有出现新的、可复现的入口、事务、恢复或适配器缺口，且在本计划登记唯一切片后才可再次进入。

### 共享玩家状态读取收口

本条是基础能力收口，不是新的玩法入口。盘点发现资产写入和背包解析已经统一到
`xiuxian/utils/assets.py`，资料/状态/战斗投影已经统一到 `xiuxian/utils/player.py`，但世界、冒险、生产、养成、
任务、事件、社交和竞技入口仍有少量玩家数值直接使用 `int(player[...])` 或 `int(row[...])`。这些路径在缺少列、
布尔值或数据形状变化时会与资料和战斗投影产生不同结果。

本条只修改上述玩家读取入口，统一使用 `player_integer`；不改变任何内容数值、门槛、奖励、战斗规则、
资产事务、宗门公共钱包或玩家可见文案。物品发放/扣除、灵石增减继续复用 `utils.assets` 和
`utils.player` 的既有状态事务；切磋与训练傀儡仍为只读观战，正式 PvP/PvE 结算不在本条改写。

文件边界：`xiuxian/utils/player.py` 的既有读取入口及其调用方，包括 `world/`、`adventures/`、`exploration/`、
`production/`、`progression/`、`advancement/`、`routine/`、`quests/`、`events/`、`livelihood/`、`social/`、
`specials/` 中本次扫描到的玩家数值读取，另含 `test/test_utils.py`、本状态页和本计划。共享状态审阅子代理只读
核对了绕过点和宗门资产边界，未修改工作树；主线负责代码、测试和最终验收，避免多个代理同时改同一仓储。

验收为共享读取投影测试、相关领域回归测试、玩家字段直读扫描、`compileall`、全部内容 JSON 解析和
`git diff --check`。
本条不新增运行时版本标识，不添加旧格式兼容分支。完成后基础能力进入冷却；若未来发现新的绕过点，须
登记具体行为差异后再单独修复，不能借机重构已闭合玩法。

### 已闭合切片：领域前线真实战斗结算

本条是对既有玩家路径缺陷的修复例外，不按事件子插件或实施计划顺序续做。审计确认原 `开始领域战` 在
`domain_front_repository.py` 直接插入固定胜利和固定贡献，没有正式会话、行动回放或战后结算；
`enemy.domain_front_guardian` 缺少内容记录，来源查询还会把同地点的其他正式胜场认作领域前线来源。
现已补齐敌人内容并复用共享战斗 application/repository 创建、推进和结算正式自动 PVE；战斗会话与事件轮次、
角色和事件请求关联在战斗创建事务中写入。胜负、装备耐久和战后状态只由正式战斗结算决定，只有关联到本轮/本人/
`pve.domain_front` 的胜利可记为战斗贡献。

跨域候选比较：其他三界多人副本和悬赏矩阵仍缺完整规则/奖励合同，且冒险/战斗刚有误选的悬赏切片；道统服务剩余
三条图鉴见闻缺稳定来源和奖励，图鉴域近期已改；Web 和跨服写入仍锁定且安全/恢复合同未闭合；宗门创建参数属于
近期已活跃社交域中的低影响内容收口。它们都不比固定伪胜利更适合先做。本条只准处理下列边界，不借机扩展这些候选。

入口和文件所有权：玩家入口 `开始领域战`；主线文件为 `data/战斗/敌人.json`、战斗敌人解析/校验、
`xiuxian/application.py`、`xiuxian/combat/use_cases.py`、必要的 `combat/repository.py` 自动恢复接口、
`xiuxian/events/domain_front_use_cases.py`、`domain_front_repository.py`、`domain_front_migration.py`、
`adventures/repository.py` 中领域战证据读取、`test/test_domain_front.py`、战斗/内容专项测试及本计划、
当前状态、战斗/事件合同文档。主线代理拥有这些文件并负责最终合并与验收。

明确排除：占点流程、活动轮次/胜负/领奖、领域赛季、领域核心兑换、领域前线主线、其他公共事件、
悬赏矩阵、多人 PVE/PvP 规则、训练傀儡和切磋观战。不得改变正式 PvP/PvE 通用伤害或奖励规则；不得使切磋/
训练傀儡产生邀请、状态变化、费用、奖励或图鉴写入。

验收已通过：QQ 官方和 OneBot V11 均走实际 `开始领域战` 命令链并创建正式战斗会话/行动记录；自动推进与正式 resolve
决定胜负，战败不产生战斗贡献。相同请求重放恢复同一场战斗、同一事件投影；覆盖会话创建后重启、行动写入后重启、
战斗结算后但事件投影前重启；注入关联写入故障后，战斗会话和 operation 原子回滚，并可用原请求重试。同地点异类型
正式胜场被拒，弱角色正式战败不产生贡献。专项测试为
`test/test_domain_front.py`；玩家回复不暴露内部战斗编号、稳定键或开发词。正式 PvP/PvE 通用结算与切磋、训练傀儡
只读观战未改；无旧格式兼容分支。

子代理协作采用只读审阅而非并行编码：`candidate_rotation_audit` 横向比较未闭合域和近期目录记录；
`domain_front_battle_audit` 核对固定胜利、敌人引用、双适配器测试和宽泛来源回退；恢复/关联方案审阅代理只核对
战斗 operation 窗口、持久链接与证据查询边界。子代理不修改工作树；一个事务跨事件/战斗仓储，故不拆分编码所有权，
由主线统一实现并重新运行全部门槛。剩余缺口：若本切片覆盖不了多人协同领域战，不新增入口，另行登记独立合同。

本轮完成后事件/战斗领域进入冷却；当时尚未登记下一条切片。后续选择须从当前状态页所有未闭合玩家路径重新横向比较，
不会默认沿事件插件、战斗插件或本计划的历史编号继续开发。下一条切片须重新登记在当前状态页和本计划开头。

### 已闭合切片：宗门设施业务日维护

本条修复洞天二层已开放设施路径的事务缺口。宗门成员可用 `认领设施槽位 <设施> 宗门` 锁定宗门所有的设施，
但 `维护设施` 的玩家 application/repository 仅查询个人槽位，导致维护入口返回未认领；已有全局 repository 维护
事务能扣宗门灵石，却没有玩家入口调用。QQ 官方与 OneBot V11 均已在独立 runtime 复现。生产合同已定义每日每槽
100 灵石、余额不足停用且不取消进行中订单。

轮转比较：最近五条闭合切片依次触及装备、经济、世界移动、事件/战斗、冒险/战斗；战斗/冒险在其中两条触及，
继续冷却，生产未被触及。选择宗门设施维护是因为它有完整合同、公开认领入口和双适配器可复现失败。生产订单
过期后先开新单会遮挡旧单恢复，虽也有 runtime 复现，但暂缓为独立生产状态机缺陷，本条不修改订单恢复或准入。
其他三界多人副本/悬赏矩阵合同未闭合；道历/机缘、装备、经济、世界移动和事件/战斗处于近期冷却；Web 与跨服
写入仍锁定，均不优先于此已开放路径。

范围与文件所有权：只改 `xiuxian/production/facility_use_cases.py`、`facility_repository.py`、
`xiuxian/utils/assets.py`、`test/test_production.py`、`test/test_utils.py` 和本计划/当前状态。
适配器和统一 application 已接入同一设施用例，不另写命令分支。统一个人/宗门设施的日维护事务，成员只能触发自己当前宗门及个人设施，
沿用 `slot_id + business_date` 的既有去重边界，并由共享资产工具扣除宗门灵石。全局维护与玩家入口共用 repository
结算逻辑。不得改宗门其他玩法、生产订单快照/恢复、设施规则、其他领域或正式 PvE/PvP；切磋和训练傀儡仍只读观战。

验收已通过：QQ 官方和 OneBot V11 真实命令链覆盖宗门认领/维护、同日重放、非成员隔离、欠费停用与次日恢复；共享宗门
货币扣减工具覆盖余额不足、无效数量和停用宗门；维护记录写入故障会原子回滚钱包、槽位和 operation，修复后同一 operation
可重试。玩家入口与全局维护共用单槽结算，个人设施回归保持通过。测试为 `test/test_production.py`、`test/test_production_contract.py`
和 `test/test_utils.py`，共 78 项通过；`compileall`、46 份内容 JSON 解析和 `git diff --check` 均通过。

本条已闭合，生产域进入冷却。生产订单过期后再开新单的恢复顺序仍是已复现但暂缓的独立缺口；下一轮重新比较所有未闭合玩家路径，
不自动沿生产或某个子插件续做。

### 上轮横向审查：暂无符合条件的代码切片

最近五条已闭合切片按新到旧触及生产、装备、经济、世界移动和事件/战斗，主领域各不相同；开发不按文档顺序或子插件目录顺序推进。四个只读审查任务分别核对活动/剧情/图鉴、修炼/养成、其他冷却外开放路径以及 `partial`/`contract`/`locked` 候选，没有发现同时满足“冷却外、真实玩家入口、当前领域合同完整、可复现运行缺口”的下一条切片。

已复现的生产订单恢复顺序问题为：订单 A 过期并转为 `expired` 后创建进行中订单 B，执行恢复时较新的 B 被优先选中并返回未到恢复时间，遮挡已可恢复的 A。现有专项只覆盖单笔过期订单。该问题虽有真实入口、现行合同和复现证据，但生产刚完成宗门设施维护且处于冷却，因此暂缓至下一轮全域比较；不把它作为本轮重入理由。问道行卷属于道历/机缘冷却域，且存在规则内容化和适配器验收缺口；其他三界多人副本、悬赏矩阵、魔渊深层和竞技场高阶资源链合同未闭合；Web 写入与跨服能力仍锁定。它们均不满足当前开工条件。

协作采用四项只读审查：`activities_path_audit` 核对活动、剧情和图鉴；`growth_path_audit` 核对修炼与养成；`untouched_domain_audit` 核对未触及的开放域并复现生产恢复顺序；`contract_candidate_audit` 对照未开放候选的现行合同。代理均未编辑运行时代码、测试或文档，当时没有并行编码，也没有登记新的唯一切片。

### 已闭合切片：锁定库存不可被再次使用或上架

本条是经济域冷却期内的正确性例外，不是按文档或目录顺序续做。横向候选比较如下：生产订单 A 过期后被较新的进行中订单 B 遮挡恢复，虽有 runtime 复现和现行恢复合同，但生产刚闭合宗门设施维护，暂缓冷却；角色创建与引路任务的 operation、来源核验、奖励事务和 QQ/OneBot 路径已闭合；其他三界副本、悬赏矩阵、魔渊深层及竞技场高阶资源链合同不完整，继续保持入口关闭；活动、剧情、图鉴和修炼/养成只读审查没有发现符合条件的缺口。经济域近期刚修复求购创建内容改名后的 operation 回放，默认冷却；但只读审计在 QQ 官方与 OneBot V11 均复现已锁库存仍能被再次使用或上架，并导致市场成交成功而求购交付失败、买家资产回退，属于可观察的资产正确性问题，符合冷却例外条件。

复现路径为卖方仅持有 1 个可交易物品，匹配求购后库存锁已建立，随后仍可发布摆摊或拍卖；另一条路径是摆摊锁住唯一一件可使用灵食后，`使用` 仍扣空背包，买家成交因库存不足失败。现有 `utils.assets` 只校验和提交资产增减，不聚合跨摆摊、求购、拍卖三类预留；该 helper 必须在资产工具中统一提供，不能由各命令继续复制不同 SQL。求购匹配已正确计算三类锁，本条改为调用共享查询，不重写其订单状态机。

文件所有权限定为 `xiuxian/utils/assets.py`、`xiuxian/economy/repository.py`、`economy/purchase_order_repository.py`、`economy/auction_repository.py`、`items/repository.py`、相关持久化错误与物品用例映射、`test/test_inventory_lock_isolation.py`、必要的 `test/test_utils.py` 及本计划/当前状态/经济用例合同。主线独占实现和测试夹具；子代理只读核验了库存锁缺口、角色/任务未选理由和跨模块边界，不并行编码，因为修复须保持同一库存查询和交易事务的一致口径。

验收通过：`test/test_inventory_lock_isolation.py`、`test/test_utils.py`、`test/test_purchase_order.py`、`test/test_auction.py`、`test/test_items.py` 共 92 项；两种适配器均覆盖交易锁交叉隔离、唯一灵食使用拒绝、剩余库存可用、锁释放后同 operation 执行、operation 写入故障原子回滚/原 operation 重试、runtime 重建后的持锁重放。切磋和训练傀儡继续只读观战，正式 PvP/PvE 结算未改；不新增运行时版本标识、开发口吻的玩家文案或旧格式兼容分支。

经济域在本条例外闭合后进入冷却；生产订单过期恢复遮挡仍是已复现候选，但生产刚闭合且需冷却，未登记下一条唯一切片。下一轮从全体未闭合玩家路径重新比较，不顺着经济子插件继续开发。

### 已闭合切片：派遣结算只记录实际所得

本条修复已开放派遣的结算结果不准确，不重做派遣子插件。旧内容测试在接受后才改小地点上限，因此快照仍要求按原上限结算，旧断言不是封顶错误证据。新增真实命令复现使用 `specials.dispatch.dao_service`：接受前地方名望/服务信誉为 `996/98`，成功奖励请求 `+8/+4`；共享状态事务实际封顶到 `1000/100`，repository 原先却会在 assignment 结果、operation 和玩家回复里写请求值。`utils.player.grant_player_reward_actual` 已提供同事务的实得差值，缺口在派遣结算没有使用该结果。

横向候选比较：生产订单 A 过期后被较新的进行中订单 B 遮挡恢复已有运行时复现及完整合同，但生产刚完成设施维护，遵守冷却暂缓；问道行卷仍有规则内容和双适配器验收缺口，但属于近期处理过的道历/机缘域，且当前问题主要是内容收口；其他三界多人副本、悬赏矩阵、魔渊深层和竞技场高阶资源链缺少当前完整合同，入口继续关闭；Web/跨服写入口仍锁定。最近五条切片是经济、生产、装备、经济和世界移动，特色玩法/派遣未在其中，且本条有可复现的数值正确性错误，优先于这些暂缓项。

入口为 QQ 官方与 OneBot V11 的 `结算派遣` 命令。文件边界限于 `xiuxian/specials/dispatch_repository.py`、派遣专项测试、本计划、当前状态页及派遣领域说明；复用 `grant_player_reward_actual`，冻结的 assignment 内容快照不改。operation 结果、assignment 结算结果与玩家回复一致记录实得数值、声望和返还；图鉴发现仍按冻结内容同事务写入。`test/test_dispatch_content.py` 与 `test/test_dispatch.py` 共 14 项通过：两种适配器覆盖名望/信誉封顶、资源返还封顶、assignment/operation/回复一致、operation 幂等与 runtime 重建回放；QQ 官方还覆盖账本写入故障时声望与图鉴原子回滚及原 operation 修复重试。明确未触碰派遣接受/取消、风险与奖励配置、日限额、活动来源投影、功业/七日目标、正式 PvE/PvP 结算以及切磋/训练傀儡只读边界。编译、全量内容 JSON 解析和 `git diff --check` 均通过；未新增运行时版本标识或旧格式兼容分支。

协作方式：本轮由主线独占仓储与测试修改，不并行编码；此前只读候选审查用于比较跨域候选。缺陷已由当前 repository、共享 helper 和现有合同定位到单一结算边界，另行拆分同一仓储没有收益。特色玩法进入冷却；下一条从全部未闭合玩家路径重新比较，不按文档或子插件目录顺序续做。

### 已闭合切片：生产订单过期恢复不被新订单遮挡

入口为 QQ 官方与 OneBot V11 的 `恢复生产`，底层沿用 `production.complete_production` / `recover_production` application 和 `_settle_production_once` 事务。当前 repository 在领取与恢复中都取玩家最新一笔 `processing`/`expired` 订单；恢复逻辑遇到这笔未满 24 小时即返回 `PRODUCTION_NOT_READY`，即使更早的一笔 `expired` 订单已可恢复。现有 `test_production_failure_refunds_inputs_and_expired_recovery` 仅覆盖单笔订单。领域合同已要求已过期订单按创建快照恢复、操作幂等及产出原子写入，但未定义积压多笔的先后；本条补充并实现：`expired` 记录与结束时间超过 24 小时的 `processing` 记录均为可恢复项，每次选择其中创建时间最早的一笔；尚未达到恢复时间的 `processing` 订单不参与选择，不能遮挡更早的可恢复项。若没有可恢复订单但仍有待处理订单，保留现有“尚未达到恢复时间”错误；没有待处理订单则保留“无待恢复订单”错误。

横向候选：问道行卷仍有硬编码周期/积分/奖励及非双适配器来源测试缺口，但未发现结算错误，本轮不以内容迁移优先于已复现的资源恢复阻塞；其它三界副本、悬赏矩阵、魔渊深层和竞技场高阶链合同不完整，入口保持关闭；Web 与跨服写入继续锁定。**开工前**最近五条切片依次涉及特色玩法、经济、生产、装备和经济；生产只出现一次，未触发子插件两次冷却条件。特色玩法与经济刚闭合，均未自动续做。生产订单恢复虽处于此前登记的冷却暂缓项，但期间已有装备、经济和特色玩法切片，且存在真实双适配器复现，因此重新进入候选有独立依据。**本条闭合后**最近五条切片依次为生产、特色玩法、经济、生产和装备；生产现出现两次，进入冷却。选择顺序来自全域候选与轮转约束，不按文档行号或子插件目录顺序。

文件边界限于 `xiuxian/production/repository.py`、生产用例合同、`test/test_production.py`、本计划和当前状态页。先加双适配器回归复现 A 已 expired、B processing 且未到恢复时间的阻塞；修复后验证恢复 A 不改变 B，再恢复 B、产出/退款只提交一次、同 operation 重放和 runtime 重建回放。写入故障须保持订单、玩家资产及 operation 原子回滚，原请求可重试。明确不触碰配方 JSON/规则、创建/取消流程、设施维护、生产委托、其他领域、正式 PvP/PvE，以及切磋/训练傀儡只读观战边界。

验收已通过：`test/test_production.py`、`test/test_production_contract.py`、`test/test_utils.py`、`test/test_documentation.py` 共 82 项通过。QQ 官方与 OneBot V11 均覆盖 A/B 顺序、B 在 A 恢复后仍保持 `processing`、A 与 B 分别结算、operation 故障回滚与原 operation 重试、operation 幂等和 runtime 重建回放；A 重放不会重复变更背包。恢复查询、资产结算与 operation 仍共用原事务。`compileall`、46 份内容 JSON 解析和 `git diff --check` 均通过。本条不改配方内容、创建/取消、设施维护、生产委托、正式 PvE/PvP 或切磋/训练傀儡只读边界。无运行时版本标识或旧格式兼容分支。

协作方式：由主线独占一个 repository 与对应测试，不并行编码；恢复选择和结算共用同一事务，拆分同一查询会造成重叠所有权。切片已闭合，生产进入冷却；下一轮重新比较全部未闭合玩家路径，不沿本子插件续做。

### 已闭合切片：道源任务内容合同与结算快照

不按文档顺序续做。开工时已有 `完成道源任务 守界/建设/传承` 公开入口，但任务目标和奖励在 `quests/rules.py` 另有 Python 常量；任务 JSON 关闭后仍可增加进度，编辑奖励也不会改变结算。`quests/repository.py` 的高阶任务展示与 `progression/cultivation_repository.py` 的渡劫 L9→L10 资格同样引用硬编码目标。该缺口横跨一个任务事务及其资格读取，不是道源秘境或战斗缺口。

候选轮转基于最近十条玩法切片，提交、领域、子插件与适配器明细见当前状态第 4.0 节。`utils` 3 次，生产/经济各 2 次，其他代码子插件各 1 次；世界移动域含一次纯地点配置共两次，不能算作两次仓储重构。最近五条无重复子插件；任务/境界晋升未在十条窗口内触及。生产订单恢复、经济库存和世界移动的可复现缺陷均已由最近切片闭合，不能作为新任务重入；社交超时只延迟状态投影且时间门槛仍有效；切磋/训练傀儡只读观战与正式 PvP/PvE 结算已有各自闭合路径。功法来源没有现行发放合同，问道行卷内容合同不完整，其他高阶副本/资源入口仍锁定，这些候选先补合同或保持关闭。选择道源任务是因为它仍有真实公开入口、当前 JSON 合同可补齐，且错误影响资产结算与 L9→L10 资格；共用任务 application/repository 和 `utils.player.grant_player_state` 可直接承接，不新增共享工具。

文件所有权仅限 `data/任务/任务.json`、`quests/rules.py`、`quests/endgame_repository.py`、`quests/repository.py`、任务 DTO/用例、`progression/cultivation_repository.py`、`test/test_endgame_producers.py`、`test/test_dao_origin_task_content.py`、涉及道源资格的专项测试、状态页、现行总表/事件任务合同、内容合同与本计划。新操作先核对 operation replay，再校验任务当前开放状态；JSON 严格提供正整数目标、完整奖励与有效物品引用。首次有效进度在当前赛季冻结名称、目标、奖励、物品/见闻展示名和赛季到 `quest_progress` 及每条任务事件；后续同赛季操作使用该快照，历史资格也从事件快照读取。关闭任务阻止新操作，但已存 operation 仍返回首次冻结结果。奖励继续通过 `utils.player.grant_player_state` 在同一 SQLite 事务写入；不复制物品、货币或角色数值 SQL。

明确不改道源秘境节点/成本/战斗、证据生产者、已有图鉴条目来源、三次天劫战与终局战规则、问道行卷、社交、经济、生产、世界移动及共享资产工具。切磋和训练傀儡保持只读观战，不新增邀请、状态变化、费用、奖励或图鉴写入；正式 PvP/PvE 仍沿原结算。无运行时版本号和旧格式兼容分支。

验收通过：聚焦回归 103 项，含新增道源内容专项 24 项、道源建设见闻、真实来源生产者、终局/天劫链、高阶/引路任务、内容合同、无版本标识、仓储边界、观战/战斗/竞技和文档。补充进行中关闭断言后，道源内容、无版本标识和文档专项 29 项再次通过。QQ 官方与 OneBot V11 均覆盖 JSON 奖励实际生效、同赛季中途改值仍使用首次快照、开始前/进行中/完成后关闭任务拒绝新 operation、重启后历史 operation 回放、L9→L10 按历史目标核验、坏目标/奖励/物品引用零写入、operation/任务/资产/图鉴同事务故障回滚、并发与原 operation 重试。`compileall`、46 份内容 JSON 严格解析和 `git diff --check` 通过；未宣称整仓全量测试通过。

`open_path_scan` 只读比较开放路径并发现缺口；`dao_origin_review` 只读核验快照/事务/历史资格，发现共享奖励拆分器不支持终局字段和重放展示顺序问题，主线已修复。两者未改工作树。不并行编码，因为任务验证、图鉴投影与奖励共用同一事务及测试夹具，由主线统一实现和复验。切片已闭合，任务/境界晋升进入冷却；下一轮比较功法/灵具来源、问道行卷、其他高阶副本等合同缺口，未预选新切片，不沿本子插件继续重构。

收尾并行分工：`dao_origin_review` 复核最终代码/测试与现行合同，指出两处相关版本要求，主线已移除；`long_test_runtime_audit` 只读检查额外新角色至飞升长测，确认首个 QQ 路径仍在650天修炼循环中持续推进、之后还需整条 OneBot 路径。为避免继续阻塞交付，主线主动中止该额外长测，结果为未完成，不计入通过数量。两代理未改工作树或测试库、未重复运行长测。后续按开发指南在开工时分配可独立的合同、测试、适配器或文档任务，不把并行工作都留到收尾；本轮聚焦测试不替代尚未完成的新角色长链复验。

### 已闭合切片：NoneBot 命令门禁、身份命名与重试恢复

本条按 `current-status.md` 的横向轮转结果选择，不按本文档顺序或子插件目录顺序续做。共享
`CommandRouter` 已注册约 550 个命令及别名，`adapters/nonebot.py` 仍维护约 299 项静态
`_COMMANDS`，使真实 QQ/OneBot 事件在门禁处丢失；直接调用同一 runtime 的共享 router 已证明
这些业务入口存在且由 application 负责准入。审计同时复现裸消息编号造成 QQ/OneBot 或不同机器
人的全局 operation 冲突，以及可重试失败被适配器内存去重吞掉的问题。道途名称/别名的内容合同
问题、已闭合玩法和未开放副本不并入本条。

文件边界限定为 `nonebot_plugin_xiuxian_3/adapters/nonebot.py`、`onebot.py`、`qq.py`、
事件辅助函数、NoneBot/QQ/OneBot 入口测试、本计划和当前状态。门禁在 `install(runtime)` 内从
`runtime.router.commands` 冻结派生，保持参数和前缀归一化，再把完整文本交给共享 router；不复制
application 规则、不引入第二份白名单。事件 operation ID 在归一化时使用适配器、机器人、用户、
场景和事件编号的稳定命名空间，同一事件重放必须得到相同 ID，不同适配器、机器人或用户不得冲突。
事件去重只在成功或已落账结果后保留；`retryable` 失败或 handler 异常释放同一事件的内存标记，
使原 operation 可以重试。不得添加运行时版本标识、旧格式兼容分支或开发口吻玩家文案。

子代理使用与文件所有权：`/root/adapter_audit` 负责上述适配器与事件辅助文件的实现，以及独立
的双适配器事件测试；`/root/content_contract`、`/root/slice_rotation` 仅做内容合同、冷却和候选
复核，不编辑工作树；主线负责审阅代理改动、补充边界测试、关联回归和最终验收。若实现需要调整
共享 router 或 application，必须先停止并重新登记切片，不在本条扩大范围。

验收覆盖动态注册集全量通过、原缺失命令在 QQ 官方与 OneBot V11 真实事件中到达 application、
命令参数/前缀保持一致、未知文本与非目标事件拒绝、跨适配器/机器人/用户 operation 隔离、可重试
故障后原事件成功重试且第三次仍幂等、runtime 重建后的历史 operation 回放，以及 `compileall`、
全量内容 JSON 严格解析和 `git diff --check`。适配器专项 `47` 项、事件/运输/拍卖恢复关联 `73` 项
通过；本节已闭合，适配器入口按轮转规则进入冷却。道途名称/别名内容合同另行登记，不在本条重复改动。

### 已闭合切片：普通移动快照严格恢复与通行物扣除一致性

轮转审查在 QQ 官方与 OneBot V11 真实入口复现：移动开始已扣除通行物，篡改
`travel_sessions.snapshot_json` 的 `consume_pass_on_arrival` 重复键后，`结算移动` 会再次扣除通行物。
修复范围限定为普通移动 repository/application、专项测试、当前状态、内容合同和本计划。实现使用
`utils.json_cache.decode_json_strict`，严格核验 JSON 对象、必需字段、类型、会话/起程 operation 归属及通行物扣除
语义；坏快照在资产、位置、会话状态或 operation 写入前拒绝，启程即扣的通行物不会在抵达再次扣除，结算失败回滚后
原 operation 可重试，历史成功结果在重启后只回放一次。不重新解释已冻结快照，不增加运行时版本标识或旧格式兼容分支。

明确不改云舟试炼、地点内容、移动数值、生活域短途运输、正式 PvP/PvE 结算或切磋/训练傀儡只读观战边界。
`/root/travel_integrity` 完成普通移动严格校验，`/root/travel_adapter_tests` 完成双适配器专项验证，主线完成最终
文档、边界与回归验收。

验收通过：普通移动专项 `test/test_world_travel_integrity.py` 34 项；世界/云舟/万兽山/适配器回归 38 项；魔界/虚空
路径 15 项；文档/内容/无版本标识 14 项；内容 JSON 严格解析 9 项；`compileall` 和
`git diff --check` 通过。验收覆盖 QQ 官方与 OneBot V11 的适用路径、重启恢复、operation 幂等/冲突、坏账本只读拒绝
和事务故障重试；未宣称整仓全量测试通过，其他路线和未开放领域不计入本条。

### 已闭合切片：训练傀儡观战接受只读权限上下文

这不是按文档顺序续做。训练傀儡已有只读观战合同和 repository 预览，但 application 门禁没有声明该用例无需资产写权限：`start_training_battle()` 调 `_invoke` 时沿用默认 `require_write=True`。QQ 官方和 OneBot V11 的只读上下文均可复现 `INVALID_CONTEXT`，相同上下文调用切磋则正确返回 `SPAR_SPECTATOR`。现已在 application 明确 `require_write=False`，让门禁与只读用例一致。

最近十条实际代码切片（不计纯测试提交 `2360b13`）依次为：`4b7c013` specials/utils、`7de4df0` player/progression、`e1b5459` player、`afabb94` events、`8775c7b` adventures、`d8a040b` progression、`f6dd8e6` world、`a6df3e1` adapters、`f733734` specials、`27f527c` production。`specials` 与 `player` 各触及两次，按子插件冷却暂缓；战斗只读入口不属于近期切片。

候选比较：领域前线的事件 JSON 引用了奖励包中不存在的稳定键，活动与赛季规则尚未形成完整内容快照，登记为后续合同切片；师徒本人关系查询缺少状态投影和过期邀请语义；功法来源与灵兽行囊配方缺少发放/配方合同；未开放副本、Web 和跨服写入口继续关闭。当前训练傀儡合同完整且有明确权限复现，影响两种适配器的只读上下文，优先用最小应用修复及双路径零写测试闭合。

文件所有权：主线独占 `nonebot_plugin_xiuxian_3/xiuxian/application.py`、本计划和当前状态；`combat_boundary_audit` 独占 `test/test_spar_interactions.py`，新增 `can_write_assets=False` 下 QQ 官方/OneBot V11 训练傀儡观战、全库零写及切磋对照回归。未触碰训练傀儡/切磋 repository、邀请或战斗状态、费用、奖励、图鉴；正式 PvP/PvE 仍沿原结算。无版本标识、兼容分支或玩家可见开发文案。

验收：`test/test_spar_interactions.py`、`test/test_arena.py`、`test/test_party_combat.py` 与构筑投影用例共 12 项通过。两适配器只读身份均返回训练观战结果，训练与切磋调用前后数据库 `iterdump()` 完全一致；正式 PvP/PvE 回归通过。

### 已闭合切片：灵兽消耗不能使用已预留物品

这不是按目录顺序继续开发。只读审查通过 QQ 官方与 OneBot V11 公开命令复现：卖家持有 1 份粗糙灵米，发布摆摊后库存被 `market_item_locks` 预留；喂养木鼠仍返回成功并扣空背包，订单保持 `listed`，锁定标的却已不存在。入口是 `companions.repository._feed_companion_sync`，扣除、灵兽经验/等级和 `companion.feed` operation 同属一个 `BEGIN IMMEDIATE` 事务。进一步复核发现 `_evolve_companion_sync` 也会从总背包扣蜕变材料，其中 `item.ancient_fruit` 可正常交易并可能被预留。两处都应按可用余额扣除，而不是总背包数量。

最近十条代码切片（不计纯测试提交）依次为：`b3a0ead` combat/application、`4b7c013` specials/utils、`7de4df0` player/progression、`e1b5459` player、`afabb94` events、`8775c7b` adventures、`d8a040b` progression、`f6dd8e6` world、`a6df3e1` adapters、`f733734` specials。`specials`、`player`、`progression` 各触及两次，均按子插件冷却暂缓；`companions` 未在窗口触及。领域前线缺完整活动/赛季内容快照，师徒本人关系查询缺少过期邀请投影合同，功法来源和小型灵兽行囊缺来源/配方合同，均暂缓或保持关闭。当前问题会让已预留物品被灵兽用例再次消耗；共享资产工具可提供按市集、求购、拍卖锁扣除后的统一可用量查询，故优先修复这条开放资产路径。

文件所有权：主线独占 `nonebot_plugin_xiuxian_3/xiuxian/companions/repository.py`、`xiuxian/utils/assets.py`、`xiuxian/utils/__init__.py`、`docs/gameplay/companions/model-workflow.md`、本计划与当前状态；`untouched_open_audit` 独占新文件 `test/test_companion_reserved_inventory.py`，覆盖 QQ 官方/OneBot V11 下喂养与蜕变预留物拒绝、零写、订单存续、释放后同 operation 重试与重放。`contract_close_audit` 只读复核共享锁查询、事务顺序及其他灵兽消耗边界。实现复用共享可用资产查询，不改变市场/求购/拍卖状态机、灵兽数值、战斗快照或奖励。训练傀儡与切磋仍只读观战，不新增邀请、状态变化、费用、奖励或图鉴写入；正式 PvP/PvE 照常结算。无运行时版本标识、旧格式兼容分支或玩家可见开发文案。

实现结果：`utils.assets.player_available_assets_missing` 统一保留货币原有校验，并按三类交易锁计算物品可用量；喂养和蜕变在各自原事务内先检查可用量再扣除，预留不足时保持资产、灵兽状态、operation、订单和锁不变。新增工具断言覆盖混合灵石/物品需求及三类预留；灵兽专项覆盖双适配器、失败零写、释放后同 operation 成功/重放和 runtime 重建恢复。专项与灵兽、市场、求购、拍卖及工具聚焦组 231 项通过；更新后的工具/灵兽专项/文档组 82 项通过；正式 PvP/PvE 与切磋/训练傀儡只读观战回归 10 项通过；源码与测试 `compileall`、全量内容 JSON 严格解析、`git diff --check` 均通过。

协作结果：`untouched_open_audit` 独占新增专项测试文件；`contract_close_audit` 只读核对合同、事务顺序和文档状态，确认无需重复补充子代理或选片通用规则；闭合后由 `untouched_open_audit` 只读横向盘点剩余候选，没有改动工作树。主线负责共享工具、灵兽仓储、文档同步和最终验收。候选复核未找到可直接开工的完整合同路径，下一轮优先补领域前线活动合同：当前事件缺完整奖励定义，轮次、赛季、成本、贡献和奖励门槛仍是规则常量；须先明确可变内容、冻结范围与奖励引用，再登记运行时切片。世界移动路线没有可复现的运行时错误；师徒关系列表、功法来源、小型灵兽行囊配方合同不全。`utils`、`player`、`progression` 按最近十条的触及次数冷却，灵兽本域也因本条闭合进入冷却；未开放副本和 Web/跨服写入口继续关闭。

### 已闭合切片：领域前线活动与赛季规则快照

开工依据是当前状态页的已开放玩家入口和可复现合同缺口，不按文档行号或子插件顺序推进。`event.domain_front` 当时已有 QQ 官方与
OneBot V11 共享 application/repository、正式 `pve.domain_front` 战斗结算、占点与领奖入口，但 `data/事件/事件.json` 的
`reward_key` 曾指向不存在的记录，活动规则和个人奖励也曾在 `domain_front_rules.py`、repository 与用例中重复定义；21 日赛季的
窗口、来源系数、榜单容量、排序和奖励分档也没有内容快照。该条作为一个 events 领域切片一次闭合活动和赛季，不拆成连续的内容搬迁。

本轮主线拥有 `data/事件/事件.json`、新增 `data/事件/赛季.json`、`data/奖励/奖励.json`、`events/domain_front_rules.py`、
`domain_front_repository.py`、`domain_front_migration.py`、领域内容/状态/合同文档及最终集成。规则解析必须严格校验名称、说明、
状态、地点、境界、正整数窗口/门槛/成本/贡献/目标、奖励条目、图鉴引用和赛季来源；内容关闭只阻止新轮次/新赛季，历史轮次和
赛季按冻结快照结算。未知的历史方案版本、旧字段和运行时版本标识不保留；固定命令格式、错误提示和少量回执短句留在代码。

文件边界与协作：`/root/front_adapter_tests` 独占新增 `test/test_domain_front_content.py`，只覆盖内容变更/关闭、坏 JSON/引用、
轮次与赛季快照恢复、占点来源、幂等和双适配器入口；`/root/front_content_contract` 只读核对可变字段与固定文案边界；
`/root/front_snapshot_audit` 只读核对仓储事务、数据库字段、恢复和正式战斗边界。代理均未编辑主线文件；主线统一修改规则、仓储、
迁移、内容和文档，解决边界冲突并运行全部验收。

不触碰：正式 PvE/PvP 自动战斗创建、行动、胜负、耐久与战后属性结算；战斗与角色/轮次/事件请求原子绑定；战败零贡献、跨玩家/跨轮次
来源拒绝、每来源一次；切磋和训练傀儡继续只读观战，不创建邀请、状态、费用、奖励或图鉴写入；其他事件、主线和未开放副本保持原状。

验收结果：临时内容改值、改名、关闭后新旧轮次行为分离；坏 JSON、重复键、缺字段、错误奖励/地点/境界/物品/资源引用在任何新轮次、
参与、资产或 operation 写入前失败；轮次冻结目标、时段、门槛、成本、来源贡献、领奖条件、奖励和图鉴；赛季冻结来源系数、榜单容量/排序、
奖励分档和领奖/兑换窗口。QQ 官方与 OneBot V11 均覆盖占点分钟校验、真实正式战斗胜败来源、重启恢复、同 operation 回放、不同输入冲突、
事务故障重试和坏快照零写；领域前线聚焦组 11 项、只读观战回归 5 项通过，源码与测试 `compileall`、全部内容 JSON 严格解析及
`git diff --check` 完成。旧开发数据库中新增规则快照列可能为空对象、旧占点 CHECK 约束不会由 `IF NOT EXISTS` 更新；不加入兼容分支或历史回填，
正式发布前重建开发库或执行明确迁移。整仓全量测试和新角色飞升长链不以局部结果代称。

### 已闭合切片：突破结算严格快照与 operation 互证

候选轮转发现公开入口 `开始突破 聚气` -> `结算突破` 存在可复现的资产与境界篡改：`progression/breakthrough/repository.py`
以宽松 JSON 读取 `breakthrough_sessions.snapshot_json`，重复的 `success_bp` 键可把原本失败的 roll 改成成功；QQ 官方与 OneBot V11
均已复现角色从当前境界 L10 直接晋升、扣除/发放灵石。现有突破测试只覆盖正常结果与普通幂等，没有坏快照、双适配器、重启和故障重试。

本条处理了突破开始/结算及 `progression.settle_breakthrough` operation 的严格 JSON、会话列/玩家归属/冻结字段互证和原子恢复。重复键、截断、
非对象、布尔或越界数值、错误奖励/随机种子、坏账本均在境界、修为、资源、会话终态和 operation 写入前拒绝；修复后沿原 operation
重试，成功回放不重复结算。主线拥有状态/计划文档和最终整合；`/root/candidate_rotation` 独占
`xiuxian/progression/breakthrough/repository.py` 与新增 `test/test_breakthrough_snapshot_integrity.py`，只修改该仓储和专项测试；
其他代理仅做只读合同/适配器审查。复用 `utils.json_cache.decode_json_strict`、共享角色状态事务和既有 operation 协议。

不改变突破规则、奖励数值、心魔/炼虚后续流程、正式 PvE/PvP 结算或切磋/训练傀儡只读边界；未新增运行时版本标识、旧格式兼容分支或开发文案。
QQ 官方与 OneBot V11 的专项 8 项、原突破测试 14 项、同域回归 57 项通过；覆盖损坏快照零写、operation 结果损坏只读拒绝、账本写入故障回滚、修复重试、runtime 重建和同 operation 幂等。
源码与测试 `compileall`、全部内容 JSON 严格解析及 `git diff --check` 通过；未宣称整仓全量测试或新角色飞升长链通过。

119. **已完成（跨界公共事件结算快照与 operation 互证）**：候选轮转在 `妖界贸易事件` 的 QQ 官方与 OneBot V11 真实路径复现 `world_event_rounds.result_json` 奖励数量可被篡改并实际发放的问题。事件域近期已有切片，本条以可直接改变物品/声望且有双适配器证据的正确性缺陷为例外；短途运输虽有宽松 JSON 缺口但处于近期冷却，其他活动候选没有更高影响的开放路径。

文件所有权限定为 `events/public_event_rules.py`、`events/cross_realm_repository.py`、`events/cross_realm_migration.py`、`persistence/schema.py`、`persistence/sqlite_repository.py`、`test/test_cross_realm_event_snapshot_integrity.py` 及本计划/当前状态。每轮事件新增冻结配置摘要；`public_event_snapshot` 使用 `utils.json_cache.decode_json_strict`，`validate_public_event_round` 互证事件键、地点、目标、成功标记、配置结构、摘要和贡献总账。贡献、查询、结算和领奖在任何资产、贡献记录、领取记录或 operation 写入前拒绝坏 JSON、重复键、截断、错误类型及摘要/轮次字段不符；operation 回放严格解码并互证公开角色归属、领取轮次和奖励账本。配置摘要只绑定冻结内容，不是运行时版本标识；未发布项目不增加旧格式兼容分支，旧开发库需在正式发布前重建或按明确迁移处理。

专项测试 22 项与既有跨界事件测试 7 项通过，覆盖 QQ 官方与 OneBot V11、损坏轮次快照/轮次列/operation 的零写、修复后同 operation 重试、重启恢复及幂等。主线负责运行时代码、持久化和最终验收；`/root/candidate_rotation` 只写独立专项测试并复现双适配器缺陷，`/root/companion_path_audit` 只读审查短途运输候选，未改同一仓储。正式 PvE/PvP 结算、切磋/训练傀儡只读观战和其他事件状态机不在范围内。

120. **已完成（雾隐试炼塔冻结奖励与领奖账本互证）**：QQ 官方与 OneBot V11 的真实 `挑战试炼塔` / `领取试炼塔奖励` 路径复现 `tower_runs.reward_json` 宽松解析下重复 `spirit_stones` 键把每层 10 灵石改成 9999 实际入账，且被改写的领奖 operation 结果会被当作历史回放。特色玩法域近期已闭合虚空塔，本条以可直接改变资产且有双适配器证据的正确性缺陷为例外，不重开塔层规则、额度、准入或自动回合引擎。

文件所有权限定为 `specials/tower_repository.py`、`specials/tower_rules.py`、`specials/tower_migration.py`、`test/test_tower_snapshot_integrity.py`、`test/test_tower_snapshot_migration.py`、`test/test_tower.py` 断言及本计划/当前状态。塔局新增覆盖冻结奖励与地方名望上限的 `reward_digest`，由 `tower_rules.reward_snapshot_digest` 单点生成，迁移按已存快照回填历史行且拒绝回填含重复键或坏类型的快照；运行投影、领奖与 operation 回放统一 `decode_json_strict` 并互证塔局列、玩家归属、楼层、首通标记、战斗结果、领奖记录与账本结果。摘要只绑定冻结数值，不是运行时版本标识，也没有按当前内容重算历史奖励的兼容分支。

专项 1 项与升级/迁移专项 3 项、试炼塔与适配器同组 49 项、严格 JSON 与 operation 家族加竞技回归 179 项、图鉴/虚空塔/内容/工具/文档/无版本标识 121 项通过，覆盖双适配器坏快照零写、故障后同 operation 重试、runtime 重建幂等回放与坏历史行修复重放；源码与测试 `compileall`、全量内容 JSON 严格解析及 `git diff --check` 通过；未宣称整仓全量测试或新角色飞升长链通过。主线独占上述运行时代码、两份塔专项测试与文档；三个子代理因上游模型渠道不可用未产出任何文件，未发生并行改同一仓储的情况。

121. **已完成（适配器投递失败释放事件去重）**：`adapters/nonebot.py` 原先只在 dispatch 异常或可重试结果时释放事件去重标记，`send_markdown_message` 自身抛错时标记保留且异常交回 NoneBot，导致 QQ 官方与 OneBot V11 的传输重试被去重吞掉：玩家收不到回复而角色状态已变。现改为发送异常先释放该事件标记再抛出，`matcher.finish()` 控制流异常不释放，成功回复后的重复事件仍被抑制。`test/test_adapter_normalization.py` 新增 2 项覆盖两种分支，该文件 13 项与真实适配器模拟 23 项同组通过；不改命令派生、operation 命名、内容合同或玩法状态机，也不新增适配器专有文案。
122. **已完成（生产委托冻结快照与结算账本互证）**：QQ 官方与 OneBot V11 的真实 `发布生产委托` / `接取生产委托` / `交付生产委托` / `确认生产委托` 路径复现 `production_commission_orders.result_json` 重复 `outputs` 键折叠成 999 后实际发放 999 枚丹药，以及冻结快照质量骰重复键改写成败、托管拆分偏离报酬、被改写的 `operations` 结果被当作历史回放。经济域近期只闭合过市集入口，本条以可直接改变灵石/物品且有双适配器证据的正确性缺陷为例外，不改报酬区间、手续费、供料模式或交付时限。

文件所有权限定为 `economy/repository.py`、`test/test_economy_commission_integrity.py` 及本计划/当前状态。快照校验按是否已接取分档锁定键集合并与委托列、配方材料、能量、工具耐久和质量骰互证；结果校验按状态锁定键集合，从冻结快照重算品质、成功标记、产物与失败返还，要求交付零支付、结算 `producer_payment + platform_fee == reward_stones`、失败 `publisher_refund + platform_fee == reward_stones`、取消与过期整笔退还托管。发布、接取、交付与恢复、确认、取消、过期与列表读取统一 `decode_json_strict`，operation 回放复用 `utils/operations.py` 并与当前行投影互证，生产者 `durability_json` 同样严格解码。互证只绑定已冻结数值，不是运行时版本标识，也没有按当前内容重算历史委托的兼容分支。

专项 4 项（发布方与生产方在两个适配器间对调）与经济/生产/市集/库存锁同组 125 项通过，覆盖重复键放大、字符串产物、交付前快照篡改、`operations` 结果伪造与重复键、重启回放、零写断言与修复后同 operation 重试；源码与测试 `compileall` 及 `git diff --check` 通过；未宣称整仓全量测试通过。上一轮整仓失败项已定性：13 项在 `367ef2a` 干净工作树同样失败，其余 4 项由 `test/*.py` 复制 `data/` 时带入本机在跑的 `data/xiuxian3.sqlite3` 造成，属测试隔离缺陷。市集 `_market_operation` 的宽松 JSON 与这 4 项隔离缺陷留作下一条。
123. **已完成（测试沙箱不再带入本机运行库）**：`test/*.py` 约 150 处 `shutil.copytree` 把仓库 `data/` 复制进临时沙箱并直接作为 `data_dir`，而 `data/xiuxian3.sqlite3` 是 git 忽略、由本机在跑的机器人写入的运行库，导致 `test_dao_origin_task_content.py`、`test_livelihood_field_selection.py` 的 4 项断言读到他人 players/codex_entries/operations；同一两条文件在 `367ef2a` 干净工作树全部通过，证明差异只来自被复制的运行库。

新增 `test/conftest.py` 单点收窄：内容复制默认忽略 `*.sqlite3`、`*.sqlite`、`*.db`、`*.log`、SQLite journal/WAL/SHM、`__pycache__` 与 `.pytest_cache`，显式 `ignore` 原样透传，并保留 `shutil.copytree` 按位置参数递归子目录的行为。文件所有权仅为新增 `test/conftest.py` 与本计划/当前状态；不改断言、玩法数值、持久化合同，不新增运行时版本标识，运行时代码不使用 `shutil` 复制，产品行为不变。

上述 2 份文件 38 项与另外 10 份内容复制型测试 77 项通过，另确认 `data/` 内容全为 JSON、无测试依赖被复制的运行库；未宣称整仓全量测试通过。剩余 13 项整仓失败在 `367ef2a` 干净工作树同样失败，早于本轮严格 JSON 切片，留作下一条：其中 7 项是夹具用 SQL 直接改写境界却不做 `寻仙问道`，导致六项资质为空而探索入口返回 `PERSISTENCE_ERROR`，6 项是 `test_livelihood_service.py` 对服务订单结算 operation 标识的期望与实际不一致。
124. **已完成（陈旧测试夹具修复）**：`367ef2a` 干净工作树同样失败的 13 项整仓失败逐项复现，全部是夹具陈旧而非运行时缺陷：`_qualification` 自 `189329f` 起要求六项资质、单项 5-15、总和 60，而三处夹具只写两键大数值或不写资质；两处夹具用 SQL 改写 `cultivation_sessions.ends_at` / `travel_sessions.ends_at` 快进，被冻结快照互证直接拒绝；`test_livelihood_service.py` 写死的适配器 operation 标识与实际派生值不符。

文件所有权仅为 `test/test_beast_intro.py`、`test/test_adventures_bounty_body_trial.py`、`test/test_cross_realm_party.py`、`test/test_domain_sources.py`、`test/test_livelihood_service.py` 与本计划/当前状态。资质统一复用 `test/combat_fixtures.py::BALANCED_QUALIFICATION`，首领战强度改为 `equip_damage_weapon` 且取伤害 500 以覆盖第 3 回合污染与第 4 回合召唤后再取胜，`test_domain_sources.py` 用 `MutableClock` 推进时钟替换 `ends_at` 改写，服务结算改从结果 `operation_id` 取标识。不改运行时代码、错误码、玩法数值或持久化合同，不新增运行时版本标识。

7 份文件同组 67 项全部通过（此前同一批次 13 项失败），`git diff --check` 通过；未宣称整仓全量测试通过。此前附记“未 `寻仙问道` 角色 `开始探索` 返回 `PERSISTENCE_ERROR`”经当前代码复核不成立：探索仓储先检查角色阶段并映射为 `EXPLORATION_REQUIREMENT_MISSING`，不再作为待办。
