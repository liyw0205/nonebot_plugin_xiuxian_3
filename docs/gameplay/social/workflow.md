# 社交域：状态机

```text
application -> accepted/rejected/expired
member -> active -> left/kicked
party -> forming -> ready -> running -> settled/disbanded
service -> created -> accepted -> locked -> processing -> delivered -> settled
```

宗门职位首版：成员、执事、长老、副宗主、宗主。公共仓库、成员管理、职位和解散均需要权限与审计。

队伍中任何成员不满足地点、境界或资源条件，行动整体拒绝。队长离开按规则转移或解散，不能留下不可结算队伍。