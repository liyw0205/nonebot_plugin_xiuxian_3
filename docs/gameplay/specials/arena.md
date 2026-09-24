# 特色玩法：竞技场

竞技场是异步快照竞技：角色发布可撤销的防守快照，挑战者使用自身开始时快照与防守快照进行可回放战斗。首版不做实时匹配、押注、战利品掠夺或跨玩家资产转移；胜负只影响赛季积分、图鉴、展示、地区名望和受限服务资格。

## 1. 防守快照与匹配

`specials.publish_arena_snapshot` 要求 active 修行者、无战斗/突破/重构锁。快照保存数值、道途、技能、装备耐久、地点环境中性化、内容/规则版本，默认有效 7 天；角色之后更换装备、层数或道途不会改写已被引用的快照。玩家可撤销未匹配快照；已 queued/running 对局继续按原快照结算。

匹配池按 `arena_rating` 分段：v0.1 分为 0–499、500–999、1000–1499、1500+；只在同段或相邻段匹配，防止新角色面对高阶快照。没有合规对手时返回 `ARENA_OPPONENT_UNAVAILABLE`，不消耗挑战次数。

| `arena_mode_key` | v0.1 参数 | 奖励边界 |
|:--|:--|:--|
| `arena.spar` | 每日 5 次；单人异步；15 回合 | 积分、图鉴、名望；无灵石掠夺/修为 |
| `arena.rank` | 每周 20 次；同段匹配 | 赛季积分、展示称号、服务资格 |
| `arena.practice` | 每日 3 次；可选好友同意快照 | 无积分，仅战术记录/图鉴 |
| `arena.team` | 2v2/3v3/2v3；每日 3 次；复用已确认双人或三人竞技队伍 | 双方成员积分更新、展示；无玩家资产转移 |

## 2. 结算与反刷

战斗复用 `BattleSession`，但地点环境固定为 `arena.neutral`，禁用一次性外部消耗物、剧情旗标和未发布内容。每场最多 15 回合；平局按双方防守成功。对局结束固定胜负、积分变化、对手快照、回放和反刷计数。

积分：胜 +25、负 -10（最低 0）、平 +5；同一对手快照每日最多 2 场计分，第 3 场后只算练习。新快照至少发布 30 分钟后可被再次计分匹配；同一平台身份/同一设备关联的风控事件只能标记审计，不能自动没收角色资产。

赛季结算按冻结排行榜：积分 desc、胜率 desc、首次达到积分时间 asc、player ID asc。奖励仅为称号、展示徽记、地区名望、图鉴和服务资格；不得给修为、突破物、可交易稀有装备或终局资源。

## 3. 隐私、关闭与验收

对手只显示公开昵称、道途、境界/层数区间和快照摘要；不暴露平台 ID、背包、私密故事旗标或精确装备来源。关闭时停止新匹配，queued/running 按快照结算；赛季结算后 7 天内领奖，逾期转展示记录。

验收：发布/撤销不影响已开始对局；同快照对刷不超每日计分；挑战次数/积分/赛季奖励幂等；快照过期不能匹配；战斗结果不可被挑战者输入伤害/胜负篡改；输赢不发生玩家间资产转移。

## 4. 当前运行时切片

当前开放 `arena.spar`、`arena.practice`、`arena.rank` 和 2v2/3v3/2v3 `arena.team`，入口统一经过 application：

- `发布竞技场快照` / `撤销竞技场快照 [snapshot_id]`
- `竞技场列表` / `挑战竞技场 [snapshot_id]`
- `竞技场练习 [snapshot_id]` / `允许竞技场练习 <snapshot_id> <对手用户标识>`
- `竞技场排位 [snapshot_id]`
- `发布组队竞技场快照` / `组队竞技场列表` / `挑战组队竞技场 [snapshot_id]`
- `竞技场回放 [match_id]` / `领取竞技场结果 [match_id]`
- `组队竞技场回放 [match_id]`

竞技场对局由 `specials/arena_repository.py` 负责；结算后的知识/声誉由独立的
`specials/arena_projection.py` 在同一事务中投影到 `codex_entries`、`activity_events`、
`player_reputations` 和 `arena_projection_events`。每名参与者每场对局有唯一投影记录：
参与和胜负图鉴首见、竞技场活动记录；计分胜利增加 `local.xuantian.new_town` 地方名望 1，
练习、平局、非计分反刷对局不增加名望。投影 operation 与对局 operation 一起幂等，失败时随
对局整体回滚。对局本身使用 `arena_snapshots`、`arena_matches`、`arena_actions` 和
`arena_reward_claims`；不会创建单人 `battle_sessions`。跨服前置另外保存平台身份路由、结算审计和
只读赛季冻结快照（`arena_identity_routes`、`arena_audit_events`、`arena_season_snapshots`），
这些表不执行跨服匹配、不合并 QQ/OneBot 身份。QQ 官方和 OneBot V11 均覆盖发布、延迟、挑战、
练习授权、回放、确认、反刷和模式配额。三人以上 PvP 与跨服仍关闭。

`arena.team` 只接受已确认的 `party.exploration_pair` 或 `party.arena_trio` 队伍；双方队伍人数可以相同，也可以组成 2v3，队长发布快照并发起挑战，成员属性和装备在快照中固定。
战斗由服务端自动选择行动，结果写入独立的 `arena_team_matches` / `arena_team_actions`，不复用单人
`battle_sessions` 或队伍 PVE 会话，也不发生灵石、修为、装备等玩家资产转移。

## 5. 恢复演练与观测

竞技场前置数据提供独立的恢复仓储接口：

- `create_arena_recovery_backup(artifact_key, request_id, operation_id)` 使用 SQLite online backup 创建数据根 `backups/` 下的逻辑工件和 JSON 清单；工件记录 SHA-256、schema 摘要、表行数、内容/规则版本。
- `verify_arena_recovery_backup(artifact_key)` 拒绝绝对路径、路径穿越、符号链接、校验和/schema/行数不一致的工件。
- `restore_arena_recovery_backup(...)` 先验证工件并创建独立恢复前快照，再写入临时数据库；通过 `integrity_check`、`foreign_key_check`、对局/投影/身份路由/赛季快照/审计引用检查后才原子替换。失败不激活工件，保留原库和恢复前快照。

`arena_audit_events` 的结算 payload 和 `arena_recovery_events` 均保留 `request_id`、`operation_id`、`match_id`、`player_id`、`mode_key`、`content_version`、`rule_version`、结果/失败原因和耗时。恢复后重放历史 operation 只返回同一结果，不重复写入投影、身份路由或审计记录。恢复演练不开放跨服匹配，也不合并 QQ/OneBot 身份。
