# 战斗域：用例与验收

## 用例

`start_battle`、`run_turn`（服务端内部）、`resolve_battle`、`claim_battle_reward`、`replay_battle`；
队伍战斗另有 `start_party_battle`、`settle_party_battle`、`replay_party_battle`，不接受客户端行动。

战斗开始后由服务端自动选择合法技能和目标并推进回合。聊天客户端不能提交攻击、防御、
技能、目标、伤害或结算结果；`run_turn` 只供内部 worker/application 调用，并记录自动
策略版本、随机池和 operation ID。

具名遭遇必须在敌人定义的 `location_key` 开始；战斗快照冻结该地点。探索遭遇从探索快照
读取地点、境界、资质、属性和装备，并记录 `exploration_id`，不读取结算时的当前状态。
队伍 PVE 从已确认队伍读取所有成员快照，必须锁定每名成员资产；发起者限队长，结算者
可以是任一已确认成员，奖励按 `(battle_id, player_id)` 唯一记录。界隙副本保存每人当前
`member_status`、神魂、复起次数和贡献；倒地成员最多复起一次，复起由服务端原子扣除队友 25 点神魂并写入回放。
境界、地点或已有行动锁任一前置不满足时，不创建会话，也不能生成任务资格证据。

魔界堕落遗迹外层的单人探索使用 `enemy.demon_ruins_scout`，内容快照为 `content-0.3`、
战斗规则为 `combat-0.3.1`；它是为元婴单人探索/主线证据设置的巡守遭遇。`enemy.demon_overlord`
保留 `8000` 气血、`520` 攻击和 `combat-0.3.0`，只由有权限的 2–5 人魔渊副本启动，
不作为单人主线证据战。

## 错误码

`BATTLE_NOT_FOUND`、`BATTLE_BUSY`、`BATTLE_REQUIREMENT_MISSING`、`SKILL_NOT_AVAILABLE`、`TARGET_INVALID`、`RESOURCE_INSUFFICIENT`、`BATTLE_EXPIRED`、`BATTLE_ALREADY_SETTLED`。

## 验收

客户端伪造伤害/技能/目标被拒绝；自动行动重试不重复扣资源；超时和断线释放角色锁；探索
遭遇在 QQ 官方和 OneBot V11 上均能完成自动战斗、回放和跨重启恢复，失败不发探索冻结奖励；
队伍 PVE 必须验证成员地点/境界、队伍快照、资产锁、协助者结算权限和唯一奖励，跨重启仍可回放；
界隙回合 5/10 必须记录至少两名防御者，否则全队神魂各扣 10；魔渊每 3 回合全队污染 +8，万兽每 4 回合记录两只祖灵并由队员自动清除；复起每名成员最多一次，奖励排序、贡献和 roll 固定在结果快照；
PvP 结果使用所有参与者的开始快照并可回放；奖励领取不重复生成资产。

终局战单独由 `final_battle_sessions`、`final_battle_members`、`final_battle_actions` 和
`final_battle_rewards` 持久化，不复用单人 `BattleSession`。发起者最多邀请 4 名同在天劫台、
渡劫 L3 以上的协助者；只有发起者可开始、恢复、取消、推进或选择。创建大厅时从背包托管
1 张飞升凭证，胜利或留界分支消耗，失败、取消和大厅超时返还。守界人气血降至一半时暂停，
发起者选择 `继续` 或 `留界`，选择写入 operation ledger 且不可更改；留界分支复用
`ascension.choose_ending` 的结局历史，不增加失败天劫债。战斗失败增加 25 天劫债并冷却
7 天。成功奖励按战斗/角色唯一；协助者按贡献获得世界功勋。QQ 官方与 OneBot V11 均需
覆盖组队、选择、结算、回放和重启恢复。

天劫试炼还必须验收：三阶段边界和阶段技能均来自服务端快照；高阶资质/装备词条、债务护盾
和阶段伤害修正进入 `ActionRecord`；重复回合不重复写行动；重启后仍能从已结算
`BattleSession` 恢复并完成试炼结算；成功只增加一次道果/功勋，失败只增加一次天劫债；QQ
官方和 OneBot V11 都能完成开始、回放和结算入口。三人以上普通 PVE 和 PvP 仍是锁定切片。
