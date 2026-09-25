# 社交域：用例、权限与验收

## 用例

`create_sect`、`apply_sect`、`review_member`、`contribute_sect`、`change_role`、`leave_sect`、
`invite_mentor`、`accept_mentor`、`reject_mentor`、`graduate_apprentice`、
`create_party`、`invite_party`、`accept_party`、`reject_party`、`confirm_party`、`leave_party`、
`get_party`、`start_party_battle`、`settle_party_battle`、`replay_party_battle`、`start_service_order`、`deliver_service`、
`get_sect_war`、`register_sect_war`、`contribute_sect_war`、`claim_sect_war_reward`。

宗门战命令为 `宗门战 [轮次]`、`报名宗门战 [轮次]`、`贡献宗门战 占点|击败|运输|维修 [来源operation] [轮次]`
和 `领取宗门战奖励 <轮次>`。查询为只读操作；报名、贡献和领奖均要求可验证消息身份并使用 operation ledger。

报名只允许等级至少 4 的宗门宗主，扣除 2000 宗门灵石并冻结最多 10 人；普通成员、等级不足、重复报名或余额不足均拒绝。
贡献只能由冻结成员提交，来源 operation 必须属于本人；占点/击败/运输/维修每轮分别最多 2/3/4/4 次，
重复来源不加分。轮次结束胜方宗门增加 100 宗门功勋，个人贡献达到 20 的实际出战成员获得 30 点世界功勋。
领奖 operation 可重放；新 operation 重复领奖拒绝；24 小时后合格未领奖记录自动发放，查询数据不得暴露平台用户 ID。

当前开放的队伍为 `party.exploration_pair`、`party.standard_pve`、`party.arena_trio`、`party.boundary_realm`、`party.demon_realm` 和 `party.beast_realm`：探索队伍最多两人，普通副本队伍 4–5 人，竞技队伍最多三人，跨界副本队伍 2–5 人；创建时冻结地点，五分钟全员确认窗口，
队长退出时转移给仍在线的成员，否则队伍解散。确认后队长可在近郊或雾隐洞天发起独立队伍 PVE；
服务端冻结全体成员属性/装备、锁定资产并自动推进回合，任一已确认成员可结算，奖励按成员唯一键发放。
每次写操作均使用 operation ledger 幂等回放。

普通多人副本命令为 `创建多人副本队伍`，别名为 `创建四人副本队伍`、`创建普通副本队伍`。队伍必须有 4–5 名同地点成员；3 人确认时保持 `forming`，第 6 名成员在邀请阶段被拒绝。当前普通敌人地点为 `xuantian.outskirts` 和 `cave.mist_grotto`，开始事务使用独立 `party_battle_sessions`，保存全员快照并在自动回合结算后逐成员发放唯一奖励。

界隙队伍只能在 `cave.boundary_realm` 创建。开始前服务端校验所有成员元婴 L1、`story.mainline.three_realms` 证据、地点、30 体力和队长 1 枚 `item.soul_crystal`；任一失败整体拒绝且不扣资源。成功后保存阵营/盟约/污染/血脉/跨界惩罚、技能和版本快照，自动战斗使用 `enemy.boundary_watcher`。成员倒地进入 `downed`，存活队友可由服务端原子消耗 25 点神魂复起一次；5/10 回合时间轴要求至少两人防御，否则全队各扣 10 点神魂。失败会扣除既有疲劳成本，不掉永久装备；奖励按贡献、角色上限和固定排序独立写入且不可重复发放。

魔渊队伍只能在 `demon.fallen_ruins` 创建，所有成员需元婴 L1、持有 `access.demon.fallen_ruins`、污染低于 80 且有 20 体力；万兽队伍只能在 `beast.ten_thousand_hills` 创建，所有成员需元婴 L1、妖界声望至少 200 且有 20 体力。两类副本均使用独立队伍战斗会话，原子扣除体力并冻结污染/血脉/技能快照；`enemy.demon_overlord` 每 3 回合使全队污染 +8，`enemy.beast_ancestor` 每 4 回合召唤两只可被队员清除的祖灵。胜利奖励分别为魔核/魔界声望/世界功勋和妖血/妖界声望/世界功勋，失败进入神魂疲劳；复起、奖励唯一性和回放规则与界隙副本一致。

已确认双人或三人竞技队伍还可以由队长发布 `arena.team` 防守快照并发起 2v2/3v3/2v3 异步挑战；组队竞技场使用独立快照、
匹配和回放表，不复用队伍 PVE 会话，也不转移任何玩家资产。三人以上队伍 PvP 和跨服匹配仍关闭。

个人三界竞技场用例为 `publish_three_realms_arena_snapshot`、`list_three_realms_arena_snapshots` 和
`challenge_three_realms_arena`，对应命令 `发布三界竞技场快照`、`三界竞技场列表`、`挑战三界竞技场 [snapshot_id]`。
发布/挑战要求元婴 L1 与 `item.permit.three_realms_arena`（或等价许可旗标）；服务端冻结阵营、盟约、污染、血脉和许可，允许同阵营及跨阵营匹配，战术环境只写入回放，不结算阵营声望、物品或玩家间资产。

当前开放的师徒关系要求师傅筑基 L4、徒弟处于凡人至聚气 L6；邀请 24 小时过期，接受后为
`active`。徒弟完成入道、达到聚气 L3 并完成一次生产或常驻经营服务后，师傅可办理一次毕业，
结算地方名望、贡献和双方服务信誉，不直接发放修为或突破资源。

## 错误码

`SECT_NOT_FOUND`、`SECT_FULL`、`ALREADY_MEMBER`、`APPLICATION_EXISTS`、`SECT_PERMISSION_DENIED`、`SECT_ASSET_LOCKED`、`ROLE_CHANGE_INVALID`、`SECT_WAR_REGISTRATION_CLOSED`、`SECT_WAR_PARTICIPANT_CAP`、`SECT_WAR_REQUIREMENT_MISSING`、`SECT_WAR_ROUND_NOT_ACTIVE`、`SECT_WAR_SOURCE_INVALID`、`SECT_WAR_REWARD_ALREADY_CLAIMED`、`SECT_WAR_REWARD_NOT_ELIGIBLE`、`SECT_WAR_REWARD_EXPIRED`、`MENTOR_REQUIREMENT_MISSING`、`APPRENTICE_RELATION_CONFLICT`、`MENTOR_INVITATION_NOT_FOUND`、`MENTOR_INVITATION_EXPIRED`、`MENTOR_GRADUATION_NOT_READY`、`MENTOR_STATE_CONFLICT`、`PARTY_NOT_FOUND`、`PARTY_ALREADY_MEMBER`、`PARTY_MEMBER_CAP`、`PARTY_PERMISSION_DENIED`、`PARTY_INVITATION_NOT_FOUND`、`PARTY_LOCATION_MISMATCH`、`PARTY_CONFIRMATION_EXPIRED`、`PARTY_STATE_CONFLICT`、`PARTY_BATTLE_BUSY`、`PARTY_BATTLE_PERMISSION_DENIED`、`PARTY_BATTLE_REQUIREMENT_MISSING`、`BATTLE_CROSS_REALM_REQUIREMENT_MISSING`、`POLLUTION_TOO_HIGH`、`SOUL_CRYSTAL_INSUFFICIENT`、`SOUL_EXHAUSTION_ACTIVE`、`BATTLE_SOUL_POWER_INSUFFICIENT`、`PARTY_BATTLE_NOT_READY`、`THREE_REALMS_ARENA_REQUIREMENT_MISSING`、`SERVICE_ORDER_CONFLICT`。普通副本人数不足或地点无对应敌人时统一返回 `PARTY_BATTLE_REQUIREMENT_MISSING`。

## 验收

非管理职位不能改仓库；申请不能重复接受；队伍条件按全员检查，普通副本覆盖 4 人下限/5 人上限和第 6 人拒绝，确认超时整体失效；三界竞技场覆盖 QQ 官方/OneBot V11、元婴与许可门槛、同/跨阵营快照、服务端自动回合、回放、幂等和资产隔离；战斗必须
保存所有成员开始快照、锁定资产并写行动回放，任一协助者结算只发每成员唯一奖励；战斗期间退出被拒绝；
服务失败按约定退款/赔偿；宗门贡献重试只增加一次。
