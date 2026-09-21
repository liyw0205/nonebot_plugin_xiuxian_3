# 特色玩法域：用例与验收

## 用例

- `specials.preview_idle`、`specials.assign_idle`、`specials.claim_idle`
- `specials.preview_dispatch`、`specials.accept_dispatch`、`specials.settle_dispatch`
- `specials.record_codex_discovery`、`specials.get_codex`、`specials.claim_codex_milestone`
- `specials.preview_tower`、`specials.start_tower`、`specials.claim_tower_reward`
- `specials.publish_arena_snapshot`、`specials.challenge_arena`、`specials.claim_arena_reward`
- `specials.start_story`、`specials.choose_story_node`、`specials.claim_story_ending`

## 通用错误码

`SPECIAL_CONTENT_CLOSED`、`SPECIAL_SESSION_BUSY`、`SPECIAL_REWARD_ALREADY_CLAIMED`、`IDLE_ASSIGNMENT_ACTIVE`、`IDLE_CLAIM_TOO_EARLY`、`DISPATCH_REQUIREMENT_MISSING`、`DISPATCH_SLOT_BUSY`、`CODEX_ENTRY_UNKNOWN`、`CODEX_ALREADY_DISCOVERED`、`TOWER_FLOOR_LOCKED`、`TOWER_ATTEMPT_CAP`、`ARENA_SNAPSHOT_EXPIRED`、`ARENA_CHALLENGE_CAP`、`STORY_NODE_LOCKED`、`STORY_CHOICE_CONFLICT`、`STORY_ENDING_ALREADY_CLAIMED`。

## 验收

1. 离线收益由服务端开始/结束时间与上限计算，伪造客户端时间不能扩大产出。
2. 派遣和挂机不会直接修改两类修为、突破准备度、突破率或终局资源。
3. 同一图鉴发现只写一条首见记录；同一集合里程碑只奖励一次。
4. 同一塔层首通奖励、竞技场赛季奖励和故事结局奖励都按唯一键回放。
5. 竞技场对局固定双方快照；对局中角色修改装备/道途不会改变已开始结果。
6. 故事选择、派遣失败、挂机过期、塔战斗失败都保留可审计原因与版本，恢复不重抽。
7. 文本、按钮与 Web 入口重试同一 operation，渲染/投递失败不改变会话或奖励。