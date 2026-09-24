# 社交域：用例、权限与验收

## 用例

`create_sect`、`apply_sect`、`review_member`、`contribute_sect`、`change_role`、`leave_sect`、
`invite_mentor`、`accept_mentor`、`reject_mentor`、`graduate_apprentice`、
`create_party`、`invite_party`、`accept_party`、`reject_party`、`confirm_party`、`leave_party`、
`get_party`、`start_party_battle`、`settle_party_battle`、`replay_party_battle`、`start_service_order`、`deliver_service`。

当前开放的队伍为 `party.exploration_pair` 和 `party.arena_trio`：探索队伍最多两人，竞技队伍最多三人；创建时冻结地点，五分钟全员确认窗口，
队长退出时转移给仍在线的成员，否则队伍解散。确认后队长可在近郊或雾隐洞天发起独立队伍 PVE；
服务端冻结全体成员属性/装备、锁定资产并自动推进回合，任一已确认成员可结算，奖励按成员唯一键发放。
每次写操作均使用 operation ledger 幂等回放。

已确认双人或三人竞技队伍还可以由队长发布 `arena.team` 防守快照并发起对称 2v2/3v3 异步挑战；组队竞技场使用独立快照、
匹配和回放表，不复用队伍 PVE 会话，也不转移任何玩家资产。三人以上队伍 PvP 和跨服匹配仍关闭。

当前开放的师徒关系要求师傅筑基 L4、徒弟处于凡人至聚气 L6；邀请 24 小时过期，接受后为
`active`。徒弟完成入道、达到聚气 L3 并完成一次生产或常驻经营服务后，师傅可办理一次毕业，
结算地方名望、贡献和双方服务信誉，不直接发放修为或突破资源。

## 错误码

`SECT_NOT_FOUND`、`SECT_FULL`、`ALREADY_MEMBER`、`APPLICATION_EXISTS`、`SECT_PERMISSION_DENIED`、`SECT_ASSET_LOCKED`、`ROLE_CHANGE_INVALID`、`MENTOR_REQUIREMENT_MISSING`、`APPRENTICE_RELATION_CONFLICT`、`MENTOR_INVITATION_NOT_FOUND`、`MENTOR_INVITATION_EXPIRED`、`MENTOR_GRADUATION_NOT_READY`、`MENTOR_STATE_CONFLICT`、`PARTY_NOT_FOUND`、`PARTY_ALREADY_MEMBER`、`PARTY_MEMBER_CAP`、`PARTY_PERMISSION_DENIED`、`PARTY_INVITATION_NOT_FOUND`、`PARTY_LOCATION_MISMATCH`、`PARTY_CONFIRMATION_EXPIRED`、`PARTY_STATE_CONFLICT`、`PARTY_BATTLE_BUSY`、`PARTY_BATTLE_PERMISSION_DENIED`、`PARTY_BATTLE_REQUIREMENT_MISSING`、`PARTY_BATTLE_NOT_READY`、`SERVICE_ORDER_CONFLICT`。

## 验收

非管理职位不能改仓库；申请不能重复接受；队伍条件按全员检查，确认超时整体失效；战斗必须
保存两名成员开始快照、锁定资产并写行动回放，任一协助者结算只发每成员唯一奖励；战斗期间退出被拒绝；
服务失败按约定退款/赔偿；宗门贡献重试只增加一次。
