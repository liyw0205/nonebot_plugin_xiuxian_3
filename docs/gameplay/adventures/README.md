# 核心：冒险、主线与战斗记录域

本域把已有的悬赏、秘境与战斗日志正规化，并新增主线关卡。它复用探索/战斗域的快照与结算，不复制第二套战斗引擎。

当前开放草药补给、生产订单、v0.2 云铁矿区/洞天精英悬赏、v0.3 魔界救援与妖界栖地悬赏、v0.1 两个秘境、v0.2 雾隐洞天二层与云舟秘境、v0.3 `instance.secret_realm.boundary_rift` 界隙裂隙秘境、`instance.secret_realm.demon_abyss` 魔界深渊秘境、v0.4 `instance.secret_realm.ancient_domain` 远古洞天和 `instance.secret_realm.ancestral_hall` 祖灵殿、v0.5 `instance.secret_realm.void_ruins` 虚空遗迹与 `instance.secret_realm.time_fort` 时序堡垒、v0.6 `instance.secret_realm.dao_origin` 道源秘境、`instance.secret_realm.heaven_echo` 天劫回音，以及 `instance.legacy.demon_reliquary` 和 `instance.legacy.demon_abyss_echo` 两条线索驱动遗府。虚空遗迹使用独立仓储、专用 2–5 人队伍、十节点路线、两场自动战、托管锚和系统补偿；专项 QQ 官方/OneBot V11 双方向与重启恢复测试见 `test/test_void_ruins_secret_realm_v05.py`。祖灵殿专项见 `test/test_ancestral_hall_secret_realm_v04.py`，时序堡垒专项见 `test/test_time_fort_secret_realm_v05.py`，道源秘境专项见 `test/test_dao_origin_secret_realm_v06.py`。遗府使用遗府专属仓储和稳定键隔离，现无已登记且规则闭合的后续副本待办。斗法记录分享和尚未定义合同的后续内容仍保持锁定；世界/社交域以其他稳定键独立开放的副本不代表相应秘境合同已开放；具名遭遇和天劫试炼的战斗会话由战斗域统一管理，状态总表见[当前开发状态](../../current-status.md)。

当前运行时已开放 v0.1 的 `bounty.herb_supply`、`bounty.craft_order`，v0.2 的 `bounty.cloud_mine`，以及 v0.3 的
`bounty.demon_relief`、`bounty.beast_habitat`：悬赏榜为只读查询，
接取时冻结目标、奖励、展示信息、地方名望键与上限，以及背包/生产/战斗/派遣基线。领取与进度
只读取该快照，资产、数值、阵营/地方名望和服务信誉交由共享角色状态事务处理；悬赏、图鉴与
operation 同事务提交，结果只记录封顶后的实得奖励。坏快照或声望 JSON 不会被当作空对象继续结算，
账本故障回滚后原 operation 可重试；过期结果也写入账本并可稳定重放。各悬赏按自身每日次数限额
计算，同一时间只能承接一桩；重复 operation 只回放原结果。

元婴 L1 可通过 `三界主线` 查看 `story.mainline.three_realms`，使用
`开始三界主线 调停|契约|共生 序号` 和 `领取三界主线奖励 调停|契约|共生 序号` 完成一条路线。
每条路线 5 关且只能选择一条；最后一关在同一事务写入主线证据、对应三界声望 1000、
`item.token.rebuild_path` 和 `story.mainline.three_realms` 旗标。开始、领取和重复请求均使用
operation ledger 幂等。

可用命令：`悬赏榜`、`接取悬赏 草药补给`、`接取悬赏 生产订单`、`接取悬赏 云铁矿区悬赏`、
`接取悬赏 魔界救援`、`接取悬赏 妖界栖地保护`、`领取悬赏`。魔界救援要求 `access.demon_abyss_gate`，以接取后新增的粗糙灵米计进度，
领取时扣除三份并原子增加魔界声望与灵石；过期不扣货。QQ 官方与 OneBot V11 共用同一 application，
妖界栖地保护要求有效 `permit.beast_trade`，只计接取后成功结算的 `dispatch.beast_relocation` 来源事件，
领奖增加妖界声望并首次发现 `codex.story.beast_habitat`。
权限、资产扣除和声望写入都在事务中完成。悬赏奖励中的
地方名望和服务信誉写入独立声誉表，不直接改境界、道途或战斗属性。

秘境命令为 `秘境预览`、`进入秘境 雾隐秘境|灵泉小径|雾隐洞天二层秘境|云舟秘境`、`选择秘境节点 资源|遭遇|选择` 和 `结算秘境`。
秘境运行时使用独立 `secret_realm_runs` 表保存节点顺序、内容/规则版本、战斗编号和票券/体力锁；遭遇节点
复用 combat 域的服务端自动回合，多遭遇路线按 run/node 索引生成独立战斗 operation。失败退还未消费的门票但保留体力消耗，
过期释放门票和体力；首通奖励只在本人第一次成功结算时发放，重复 operation 只回放原结果。QQ 官方与 OneBot V11 使用同一 application，身份和
SQLite 角色记录保持隔离。

界隙裂隙秘境使用独立 `boundary_rift_runs` / `boundary_rift_members`，不复用 `secret_realm_runs` 或既有 `cave.boundary_realm` 队伍战会话。
队伍先在 `cave.boundary_realm` 使用 `创建界隙裂隙秘境队伍` 建立 2–5 人专用队伍并完成确认；随后队长依次使用
`进入秘境 界隙裂隙`、`选择秘境节点 <节点>`，破碎岔路需追加 `内|外`，遭遇战/终局奖励使用 `结算界隙裂隙秘境`。
规则、首通/重复奖励、成本补偿与节点顺序以[v0.3 冒险内容合同](content-v0.3.md#instancesecret_realmboundary_rift-合同)为准。
QQ 官方与 OneBot V11 双方向混合队伍验收见 `test/test_boundary_rift_secret_realm_v03.py`。

虚空遗迹秘境使用独立 `void_ruins_runs` / `void_ruins_members`，不复用通用 `secret_realm_runs` 或战斗奖励。队伍在 `void.archive_ruins` 创建并确认后，队长使用 `进入秘境 虚空遗迹`，再按十节点顺序选择；两场服务端自动战由任一队员使用 `结算秘境` 续跑。入场快照冻结不稳定风险、战斗属性和版本；战败/过期保留体力和周额度但返还锚，明确系统故障才补偿体力并释放额度。规则和稳定键以[v0.5 冒险内容合同](content-v0.5.md#instancesecret_realmvoid_ruins-合同)为准。

时序堡垒秘境使用专属 `TimeFortRepositoryMixin` 与 `time_fort_runs` / `time_fort_members`，不复用通用秘境会话或虚空遗迹奖励。全员需炼虚 L1、位于 `void.archive_ruins` 并持有 `access.void.time_fort`；队长支付 40 体力，每位成员每 UTC 周尝试一次。六节点路线在 `time_keeper` 进行一场自动队伍战，时间风暴按冻结快照每三回合伤害全体存活队员；首通逐成员发阵砂并写入独立主线旗标。失败/过期保留成本和额度，明确系统故障补偿才退款并释放额度。命令及失败边界按[v0.5 时序堡垒合同](content-v0.5.md)执行。

魔界深渊秘境使用专用 `DemonAbyssRepositoryMixin` 事务，不把路线、风险、首通奖励和恢复逻辑塞入通用秘境仓储。命令为 `进入秘境 魔界深渊`、`选择秘境节点 深渊门|污染渗流|残响守卫|深渊之心` 和 `结算秘境`；要求筑基 L1、魔界深渊门地点、门禁旗标与魔界声望 200，每 UTC 周一次、入场扣 20 体力，运行 60 分钟。节点顺序、自动战、污染风险、失败/过期成本、首通/重复奖励及系统中止补偿按[v0.3 冒险内容合同](content-v0.3.md#instancesecret_realmdemon_abyss-合同)执行。战斗使用 `combat-0.3.2`，适配器覆盖 QQ 官方、OneBot V11 及 QQ→OneBot 重启续跑，详见 `test/test_demon_abyss_secret_realm_v03.py`。

祖灵殿秘境使用独立 `AncestralHallRepositoryMixin` 与 `ancestral_hall_runs` 表，不把领域事务挤入通用秘境仓储。命令为 `进入秘境 祖灵殿`、`选择秘境节点 祖灵门|誓言石阵|血脉回廊|祖灵守灵|始祖祭坛` 和 `结算秘境`；入口检查化神 L1、祖灵湖、妖界声望 3000、血脉稳定 5000 bp，单人消耗 25 体力，每 UTC 周尝试一次，60 分钟过期。首次完成只写 `story.ancestral_hall`，没有资产奖励；守灵自动战按 `combat-0.4.1` 持久化召影、自动清影和超时恢复。QQ 官方、OneBot V11 及两个身份切换方向、补偿、过期和重启续战见 `test/test_ancestral_hall_secret_realm_v04.py`。

道源秘境使用独立 `DaoOriginRepositoryMixin` 与 `dao_origin_runs` 表，不复用通用秘境仓储。角色须在 `dao.origin_gate` 达到合道 L1 并持有 `access.dao.origin`；固定八节点、60 体力、60 分钟和每角色一次。首通结算写入 `story.dao_origin` 与 `codex.dao.service_origin`，不修改任何终局资源；系统补偿才退款，普通过期保留成本和额度。命令为 `进入秘境 道源秘境`、`选择秘境节点 <当前节点>` 和 `结算秘境`。

天劫回音使用独立 `HeavenEchoRepositoryMixin` 与 `heaven_echo_runs` 表。角色须渡劫 L1 且不在最终战中；固定三节点、无体力/票券/次数成本、60 分钟过期，完成后允许重复挑战。首通结算只写 `story.heaven_echo` 结局旁线旗标，不改天劫债、终局状态或飞升资源；系统中止只结束无资源运行。命令为 `进入秘境 天劫回音`、`选择秘境节点 <当前节点>` 和 `结算秘境`，专项 QQ 官方/OneBot V11、重启和身份切换验收见 `test/test_heaven_echo_secret_realm_v06.py`。

首条遗府 `instance.legacy.demon_reliquary` 使用独立 `LegacyManorRepositoryMixin` 与 `legacy_manor_runs` 表。角色须元婴 L1、位于 `demon.fallen_ruins`、持有 `access.demon.fallen_ruins` 和绑定 `item.clue.demon_contract`；线索不消耗。固定三节点、无资源成本，60 分钟过期；失败可重试，首通只写 `story.legacy.demon_reliquary` 并关闭后续新建。命令为 `进入遗府`、`遗府状态`、`选择遗府节点 <节点>` 和 `结算遗府`；状态查询用于跨适配器/重启恢复后查看当前节点。QQ/OneBot V11 双向身份切换、重启、过期、系统中止和资源隔离见 `test/test_legacy_manor_v06.py`。

第二条 `instance.legacy.demon_abyss_echo` 在 `demon.abyss_gate` 使用既有深渊残响线索，筑基 L1 后可进入；固定三节点、60 分钟、无资源成本，首通只写故事旗标。它与契约遗府共享遗府专属会话表，但每条记录保存独立 `instance_key`；角色任一时间只能推进一处遗府。命令为 `进入残响遗府`、`残响遗府状态`、`选择残响遗府节点 <节点>` 和 `结算残响遗府`。QQ/OneBot V11 双适配器与跨适配器身份恢复见 `test/test_demon_abyss_echo_legacy_v06.py`。

v0.2 秘境合同：`instance.secret_realm.mist_depth_2` 要求金丹 L1、`cave.mist_grotto_2` 和 `item.cave_pass_advanced`，
路线为 `resource -> encounter -> choice -> encounter -> choice`，首通创建 `item.weapon.cloud_sword` 装备实例；
`instance.secret_realm.cloud_boat` 要求金丹 L1、`xuantian.floating_boat` 和 `item.ticket.cloud_boat_fragment`，
首通写入云舟图鉴和玄天新镇地方名望。两者均冻结内容/规则版本，按周限额并由 QQ 官方/OneBot V11 双适配器测试覆盖。

玄天主线已接入首章三关、城镇委托，以及云城、云铁、阵堂三段各三关：`主线道途` 查看状态，
`开始主线 <序号或关卡名>` 开始关卡，`领取主线奖励 <序号或关卡名>` 结算奖励。每次开始冻结境界、
地点、引导和地方名望上限；首通键使用 `story.mainline.xuantian:chapter:stage:player`，首通
奖励、地点/图鉴事件、称号和声誉在同一事务中提交，重复 operation 只回放结果，
重新挑战只发重复奖励。地方名望通过共享角色状态事务封顶，领奖记录与回复只保留实际所得。
关卡定义、前置、境界门槛、别名和奖励均从内容包读取。

领域前线主线已接入守界、净渊、护祖三线，每线六关：`领域前线主线` 查看状态，
`开始领域前线主线 <关卡名>` 开始，`领取领域前线主线奖励 <关卡名>` 结算。关卡前置只认
服务端已结算的领域前线参战、战斗、贡献与领奖证据；三线结局分别授予领域避难所、
魔渊净化、祖灵栖地公共项目权限与名望，不发领域能量。

虚空档案主线已接入三条八关道途：`虚空档案主线` 查看进度，`开始虚空档案主线 <关卡名>`
开始，`领取虚空档案主线奖励 <关卡名>` 结算。角色须炼虚 L1，并已由档案周任务取得
`event.archive_unlock` 解锁凭证；记录者一线还需档案守卫胜利，护航者一线读取相应的
守卫结算记录，归乡者首关另需时序堡垒首通记录。所有前置只接受服务端已结算的档案、
守卫和秘境证据，不能由客户端直接提交故事进度。首通只写档案图鉴并发放灵石，重战按
内容包给出再战所得，不发虚空晶、虚力、突破资格或终局资源。开始、结算、重启恢复和
重复请求共用主线运行记录与 operation 账本，三种适配器入口不各自维护进度。

v0.6 `story.mainline.dao_echoes` 已开放玩家流程：炼虚 L10 后可查询建设者、见证者、远行者
三线进度；每线 10 关且按线内顺序推进，开始/领取分开幂等记录。首通只增加故事事件和图鉴旗标，
不发资产或终局资格。全部 30 关的有效服务端记录可作为 `quest.dao_union` 主线组件证据。
命令为 `道源主线`、`开始道源主线 <lane> <stage>`、`领取道源主线奖励 <lane> <stage>`；完整
叙事和前置由 `data/剧情/主线.json` 实际提供，以[v0.6 冒险内容](content-v0.6.md)及[完整内容开发总表](../../content-development.md)为准。开始时冻结关卡展示和图鉴引用；内容关停只阻止新开，不影响已开始关卡领取。

## 术语映射

| 用户术语 | 修仙3稳定名称 | 稳定键前缀 |
|:--|:--|:--|
| 战斗日志 | 斗法留影 | `combat.replay` |
| 悬赏任务 | 悬赏榜 | `bounty.board` |
| 秘境 | 秘境试炼 | `instance.secret_realm` |
| 主线关卡 | 主线道途/章节 | `story.mainline` |

## 实体

`CombatReplay`：战斗 ID、参与者脱敏快照、ActionRecord 引用、摘要、分享权限、保留期和规则版本。它是只读索引，不重复结算奖励。

`BountyOffer`：业务轮次、offer、目标表达、期限、奖励快照、失败、接取者、进度来源和领取 operation。

`SecretRealmRun`：实例、入口、队伍、路线节点、门票/次数锁定、环境词缀、战斗引用、结算状态和版本。

`MainlineRun`：故事线、章节、关卡、解锁旗标、首次通关、星级/评价、快照、奖励状态和版本。

## 边界

- 悬赏和主线可发修为/普通材料，但必须走 progression/reward service，不能直接写角色字段。
- 秘境使用探索和战斗的资源锁，失败不重抽入口池；首通奖励唯一，重复挑战只给练习收益。
- 斗法留影可公开脱敏战报、个人日志和失败原因；不暴露对手平台 ID、私密故事旗标或完整背包。
- 主线关卡推进剧情旗标和地点/服务资格，不直接改变道途或飞升结局；高阶主线必须满足十层门槛。
