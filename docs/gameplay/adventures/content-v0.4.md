# v0.4 冒险内容基线：领域悬赏、深层秘境与化神主线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=adventures-0.4.0`。领域内容要求环境/领域快照，不能在结算时读取当前领域强度。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.domain_crack`：化神 L1、领域未裂 | 修复领域裂痕 2；6h；建设券、名望 +15；失败污染 +10 bp |
| 悬赏 | `bounty.abyss_defense`：领域前线许可 | 首领胜 1；8h；功勋 300、图鉴线索；每日 1 |
| 秘境 | `instance.secret_realm.ancient_domain`：全员化神 L1、3 名已确认队员 | 8 节点、每队 40 体力（队长支付）；首通领域图鉴/普通材料；每名队员每 UTC 周 1 次 |
| 秘境 | `instance.secret_realm.ancestral_hall`：血脉稳定 >=5000 bp | 5 节点；失败保留血脉快照；首通故事旗标 |
| 主线 | `story.mainline.domain_frontier` | 守界/净渊/护祖三线各 6 关；结局给公共项目权限、名望，不给领域能量 |
| 斗法留影 | `combat.replay.v0.4` | 保留 120 天/3000 场；领域战日志可查看机制摘要，不暴露其他玩家私密构筑 |

领域裂痕进行中停止同区域新秘境，但不取消已锁定实例。首通奖励唯一，失败由恢复任务结算一次。

## `instance.secret_realm.ancient_domain` 合同

该秘境使用 `content-0.4` / `adventures-0.4.1`，位于 `cave.ancient_domain`，是三人组队路线；不复用 `explore.ancient_domain` 探索池，不另行消耗 `item.domain_core`，也不重复发放普通队伍战奖励。现有 `cave.ancient_domain` 地点准入与移动成本独立执行。

入场要求一个已确认、恰有 3 名成员的 `party.secret_realm_ancient` 专用队伍；它与 4–5 人的 `party.standard_pve` 和普通 `party_battle_sessions` 分离。队长和另外两名成员均须达到化神 L1、位于 `cave.ancient_domain`、没有有效 `domain_crack`、没有其他活动秘境/冲突长行动，且均未使用本 UTC 周的本秘境额度。所有检查、队长体力扣除、成员额度预占和资产锁在一个事务内完成；队长支付全队共 40 体力，其他成员不扣体力。任一成员条件失败、队伍人数或地点不符、队长体力不足时整队零变化。已选择领域不是入场条件；每名成员仍冻结 `domain_key`（可为空）、领域力量/能量、境界、地点、阵营状态、装备/技能及内容/规则版本。

固定八节点为 `domain_approach -> fractured_gallery -> seal_archive -> primordial_garden -> domain_spring -> ancient_domain_lord -> weathered_steps -> origin_seal`。队长逐节点选择；`fractured_gallery` 可选 `inner|outer`，只写入路线快照，不修改战斗数值或奖励。节点均由服务端按序推进。第六节点启动一次 `enemy.ancient_domain_lord` 自动队伍战，使用 combat v0.4 的领域抑制和三人快照；客户端不能提交行动、伤害或胜负。其他节点不产生独立奖励或随机抽取，路线随机池为 `none`。战斗启动 operation 固定为 `run_id + node_index`，重启继续既有战斗，不创建第二场。

队员额度为每角色每 UTC 周一次；入场即预占，普通战败和 60 分钟过期均不退队长的 40 体力、不返队员额度。过期时未终结的自动战由战斗域标为 `expired` 并结算一次，避免留下活动战斗锁。清算恢复任务只能按冻结快照完成未提交节点或将异常会话终结为失败，不能重抽路线、重复扣费或发奖励。明确的系统中止可在一个事务内退还队长 40 体力、释放三名队员本周额度，并回滚本 run 已记录的领域能量变化；不覆盖会话外的新状态。活动期间三名成员均被锁定，不能换队、退出或开始冲突的长行动；`domain_crack` 之后出现也不取消已锁定实例。

仅全队战胜领域首领并完成第八节点后结算奖励。首通按角色独立判定：每名首次成功成员发现 `codex.domain.ancient_domain` 并获得 `item.ancient_fruit` ×2；再次成功每人固定获得 `item.ancient_fruit` ×1，不重复发现图鉴。失败、过期不发领域秘境奖励；本秘境上下文抑制首领普通战斗掉落，污染与血脉稳定不因秘境额外变化，领域能量仅按已记录的 combat v0.4 行动结算。首通资格、成员列表、奖励、路线、分支、费用及版本在入场快照冻结；首通标记、图鉴与资产奖励原子提交。所有入场、节点、战斗、结算和恢复操作均使用稳定 operation ID，并按队伍/角色/节点限定重放作用域。

队伍命令为 `创建远古洞天秘境队伍`；秘境命令为 `进入秘境 远古洞天`、`选择秘境节点 <当前节点>` 和 `结算秘境`。只有队长可以开始或选节点，任一锁定成员可请求结算已启动的自动战或领取全队结果。QQ 官方、OneBot V11 和两种混合队长方向必须覆盖三人数量/地点/境界/领域裂痕原子拒绝、队员周额度、队长付费、八节点顺序、领域快照与能量抑制、自动战恢复/过期终结、首通/重复奖励、战败/补偿、重启恢复、活动锁、不同输入 operation 冲突和资产隔离。完成上述运行时验收前状态为 `contract`，不得开放命令。
