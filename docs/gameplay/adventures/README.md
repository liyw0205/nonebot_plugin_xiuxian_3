# 核心：冒险、主线与战斗记录域

本域把已有的悬赏、秘境与战斗日志正规化，并新增主线关卡。它复用探索/战斗域的快照与结算，不复制第二套战斗引擎。

当前开放草药补给、训练傀儡、生产订单、v0.2 云铁矿区/洞天精英悬赏、v0.3 魔界救援悬赏、v0.1 两个秘境、v0.2 雾隐洞天二层与云舟秘境、v0.3 `instance.secret_realm.boundary_rift` 界隙裂隙秘境，以及已接入的主线关卡；
`instance.secret_realm.demon_abyss` 的规则合同已闭合但运行时仍锁定；斗法记录分享和其他 v0.3 以后的 `instance.secret_realm.*` 内容也保持锁定。世界/社交域以其他稳定键独立开放的副本不代表相应秘境合同已开放；具名遭遇和天劫试炼的战斗会话由战斗域统一管理，状态总表见[当前开发状态](../../current-status.md)。

当前运行时已开放 v0.1 的 `bounty.herb_supply`、`bounty.craft_order`，v0.2 的 `bounty.cloud_mine`，以及 v0.3 的
`bounty.demon_relief`、`bounty.beast_habitat`：悬赏榜为只读查询，
接取时冻结目标、奖励和背包/生产基线，领取时按服务端进度在一个事务中发奖。每个业务日每名
角色最多接取一条悬赏，重复 operation 只回放原结果。训练傀儡悬赏使用已结算的 `pve.training`
胜场作为服务端进度来源，接取时冻结胜场基线，完成 2 次后
领取修为和焦点丹；战斗域已有的训练战奖励仍由战斗奖励命令独立领取，不与悬赏奖励重复结算。

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

v0.2 秘境合同：`instance.secret_realm.mist_depth_2` 要求金丹 L1、`cave.mist_grotto_2` 和 `item.cave_pass_advanced`，
路线为 `resource -> encounter -> choice -> encounter -> choice`，首通创建 `item.weapon.cloud_sword` 装备实例；
`instance.secret_realm.cloud_boat` 要求金丹 L1、`xuantian.floating_boat` 和 `item.ticket.cloud_boat_fragment`，
首通写入云舟图鉴和玄天新镇地方名望。两者均冻结内容/规则版本，按周限额并由 QQ 官方/OneBot V11 双适配器测试覆盖。

主线道途 v0.1 已接入前三个不依赖战斗运行时的关卡：`主线道途` 查看状态，
`开始主线 1|2|3` 开始关卡，`领取主线奖励 1|2|3` 结算奖励。每次开始冻结境界、
地点和引导快照；首通键使用 `story.mainline.xuantian:chapter:stage:player`，首通
奖励、地点/图鉴事件、称号和声誉在同一事务中提交，重复 operation 只回放结果，
重新挑战只发重复奖励。`chapter.2.stage.1` 已登记但依赖常驻经营委托，当前返回
`CONTENT_CLOSED`，不会创建运行记录或发放奖励。

v0.6 `story.mainline.dao_echoes` 已开放玩家流程：炼虚 L10 后可查询建设者、见证者、远行者
三线进度；每线 10 关且按线内顺序推进，开始/领取分开幂等记录。首通只增加故事事件和图鉴旗标，
不发资产或终局资格。全部 30 关的有效服务端记录可作为 `quest.dao_union` 主线组件证据。
命令为 `道源主线`、`开始道源主线 <lane> <stage>`、`领取道源主线奖励 <lane> <stage>`；完整
叙事和前置以[v0.6 冒险内容](content-v0.6.md)及[完整内容开发总表](../../content-development.md)为准。

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
