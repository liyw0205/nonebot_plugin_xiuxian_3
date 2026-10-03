# 特色玩法域：共享状态机

```text
idle: preview -> running -> claimed/expired
                    -> cancelled (仅开始后 60 秒内)

闲居安排在领取前持续保存为 `running`；`claim_at` 与当前服务端时间决定是否可领取，不额外写入中间状态。

dispatch: preview -> accepted -> running -> succeeded/failed -> settled
                   -> cancelled (仅接受后 60 秒内；仍计当日配额)

codex: hidden -> discovered -> completed (集合里程碑)

tower: preview -> battle_running -> reward_pending -> claimed
                         -> lost
                         -> aborted (战斗启动失败并退还入场体力)

arena_snapshot: draft -> published -> expired/revoked
arena_match: queued -> running -> won/lost/drawn -> settled
arena_team_snapshot: draft -> published -> expired/revoked
arena_team_match: queued -> running -> won/lost/drawn -> settled

story: available -> active -> awaiting_choice -> active
                                  -> ending_pending -> ended
                                  -> expired
```

- `assigned/running/battle_running/awaiting_choice` 期间，重复请求只能返回同一会话，不可创建平行会话或二次扣费。
- `running/reward_pending` 仅允许一次领取；闲居逾时只按开始时冻结的保底所得结算，不能让奖励回到未结算状态。
- 故事关键选择一经 `locked`，相同 operation 回放原节点；不同选择或不同输入摘要复用 operation 必须返回 `OPERATION_CONFLICT`。
- 竞技场防守快照在发布时固定，后续角色属性/装备变化不会追改已经排队或正在结算的对局。
- `arena.team` 只接受已确认的双人队伍；队伍成员快照、匹配段和服务端行动在对局开始时固定，结果不写入队伍 PVE 会话。
