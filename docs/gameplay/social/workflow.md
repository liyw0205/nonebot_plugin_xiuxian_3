# 社交域：状态机

```text
application -> accepted/rejected/expired
member -> active -> left/kicked
mentor -> invited -> active -> graduated/rejected/expired
party -> forming -> ready -> disbanded
party_battle -> created -> running -> won/lost/expired -> settled
service -> created -> accepted -> locked -> processing -> delivered -> settled
sect_war -> scheduled -> open -> running -> settled
```

宗门战每周生成两轮，报名从轮次开始周一 00:00 开放至战斗开始；每轮持续 30 分钟。宗主报名时扣除
2000 宗门灵石并冻结最多 10 名 active 成员快照，普通成员不能代报名。战斗期间仅快照成员可提交
来源 operation 贡献，四类行动按固定分值和单轮次数上限计分；同一来源 operation 重放不得重复计分。

轮次结束由查询、贡献或领奖请求推进为 `settled`，按宗门总贡献固定排序并只给胜方宗门增加 100 宗门功勋。
实际出战成员贡献达到 20 可在 24 小时内领取 30 点世界功勋；窗口结束时恢复流程自动发放合格未领奖奖励，
所有状态变化和奖励均有独立 operation/claim 记录。

当前运行时开放 `forming -> ready -> disbanded/expired` 的双人探索队伍、三人竞技队伍、界隙/魔渊/万兽 2–5 人队伍状态机，
以及独立的 `party_battle` 自动 PVE 会话；队伍自身不伪装成单人战斗会话。邀请和全员确认窗口为 5 分钟，
队伍创建时保存地点和分配规则。界隙队伍只能在 `cave.boundary_realm` 创建，开始前要求所有成员元婴 L1、三界主线证据、
地点一致和资源充足；开始事务原子扣除每人 30 体力与队长 1 枚 `item.soul_crystal`，再锁定全员资产和跨界快照。
队长退出时转移给活动成员，无活动成员则解散；超时会将邀请和活动成员标记为 `expired`。

魔渊队伍和万兽队伍分别冻结 `demon.fallen_ruins`、`beast.ten_thousand_hills` 地点与 v0.3 资格；开始时每名成员原子扣除 20 体力，副本失败由结算事务统一写入神魂疲劳。

宗门职位首版：成员、执事、长老、副宗主、宗主。公共仓库、成员管理、职位和解散均需要权限与审计。

队伍中任何成员不满足地点、境界或资源条件，行动整体拒绝。战斗开始时锁定所有成员资产，
战斗期间禁止退出和其他长行动；队长离开按规则转移或解散，不能留下不可结算队伍。

师徒邀请保存 24 小时截止时间并在接受/拒绝时清理过期状态。毕业由师傅发起，要求徒弟已入道、
达到聚气 L3 且存在已完成生产或已交付常驻经营服务；毕业关系 ID 作为唯一结算键。
