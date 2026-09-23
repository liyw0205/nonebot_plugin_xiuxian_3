# 社交域：状态机

```text
application -> accepted/rejected/expired
member -> active -> left/kicked
party -> forming -> ready -> running -> settled/disbanded
service -> created -> accepted -> locked -> processing -> delivered -> settled
```

当前运行时只开放 `forming -> ready -> disbanded/expired` 的双人探索队伍状态机；
`running`、`settled` 仍属于探索/战斗后续切片。邀请和双方确认窗口为 5 分钟，
队伍最多 2 名成员，队伍创建时保存地点和分配规则。队长退出时转移给活动成员，
无活动成员则解散；超时会将邀请和活动成员标记为 `expired`。

宗门职位首版：成员、执事、长老、副宗主、宗主。公共仓库、成员管理、职位和解散均需要权限与审计。

队伍中任何成员不满足地点、境界或资源条件，行动整体拒绝。队长离开按规则转移或解散，不能留下不可结算队伍。
