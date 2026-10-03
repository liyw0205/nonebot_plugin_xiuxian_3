# 特色玩法域：用例与验收

## 用例

- `specials.preview_idle`、`specials.assign_idle`、`specials.claim_idle`、`specials.cancel_idle`（四条闲居路线已开放）
- `specials.preview_dispatch`、`specials.accept_dispatch`、`specials.cancel_dispatch`、`specials.settle_dispatch`（v0.1 三条派遣已开放）
- `specials.record_codex_discovery`、`specials.get_codex`、`specials.claim_codex_milestone`
- `specials.preview_tower`、`specials.start_tower`、`specials.claim_tower_reward`
- `specials.publish_arena_snapshot`、`specials.challenge_arena`、`specials.claim_arena_reward`
- `specials.publish_team_arena_snapshot`、`specials.challenge_team_arena`、`specials.replay_team_arena`
- `specials.get_story_status`、`specials.start_story`、`specials.choose_story_node`、`specials.claim_story_ending`（v0.1 命令为 `剧情线`、`开始剧情`、`选择剧情`、`领取剧情结局`）

## 通用错误码

`SPECIAL_CONTENT_CLOSED`、`SPECIAL_SESSION_BUSY`、`SPECIAL_REWARD_ALREADY_CLAIMED`、`IDLE_BUSY`、`IDLE_NOT_FOUND`、`IDLE_ALREADY_SETTLED`、`IDLE_CLAIM_TOO_EARLY`、`IDLE_CANCEL_WINDOW_EXPIRED`、`IDLE_DAILY_LIMIT`、`IDLE_REQUIREMENT_MISSING`、`IDLE_ROUTE_NOT_FOUND`、`DISPATCH_REQUIREMENT_MISSING`、`DISPATCH_SLOT_BUSY`、`DISPATCH_DAILY_LIMIT`、`DISPATCH_NOT_FOUND`、`DISPATCH_NOT_READY`、`DISPATCH_ALREADY_SETTLED`、`DISPATCH_CANCEL_WINDOW_EXPIRED`、`INVALID_CODEX_COMMAND`、`CODEX_MILESTONE_NOT_FOUND`、`CODEX_MILESTONE_NOT_READY`、`CODEX_MILESTONE_ALREADY_CLAIMED`、`OPERATION_CONFLICT`、`TOWER_REQUIREMENT_MISSING`、`TOWER_BUSY`、`TOWER_FLOOR_LOCKED`、`TOWER_ATTEMPT_CAP`、`TOWER_NOT_READY`、`TOWER_START_FAILED`、`TOWER_REWARD_NOT_AVAILABLE`、`TOWER_REWARD_ALREADY_CLAIMED`、`ARENA_SNAPSHOT_EXPIRED`、`ARENA_CHALLENGE_CAP`、`TEAM_ARENA_REQUIREMENT_MISSING`、`TEAM_ARENA_OPPONENT_UNAVAILABLE`、`TEAM_ARENA_DAILY_CAP`、`STORY_REQUIREMENT_MISSING`、`STORY_NOT_STARTED`、`STORY_CHOICE_NOT_READY`、`STORY_CHOICE_LOCKED`、`STORY_ENDING_NOT_READY`、`STORY_ENDING_ALREADY_CLAIMED`。

## 验收

1. 离线收益由服务端开始/结束时间与上限计算，伪造客户端时间不能扩大产出。
2. 派遣和挂机不会直接修改两类修为、突破准备度、突破率或终局资源。
3. 同一图鉴发现只写一条首见记录；同一集合里程碑只奖励一次。
4. 同一塔层首通奖励、竞技场赛季奖励和故事结局奖励都按唯一键回放。
5. 竞技场对局固定双方快照；对局中角色修改装备/道途不会改变已开始结果。
6. 固定 2v2 组队竞技场只接受已确认双人队伍，服务端保存双方队伍成员快照和行动回放，不创建单人战斗会话或转移玩家资产。
7. 故事选择、派遣失败、闲居逾时、塔战斗失败都保留可审计原因和业务快照，恢复不重抽。
8. 文本、按钮与 Web 入口重试同一 operation，渲染/投递失败不改变会话或奖励。
