# v0.6 世界地点内容基线：天劫与终局地点

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=world-0.6.0`。终局地点不允许普通撤销；每个会话由试炼/终局状态机权威结算。

| `location_key` | 准入 | 会话成本/时长 | 内容与限制 |
|:--|:--|:--|:--|
| `dao.origin_gate` | 从 `void.archive_ruins` 出发；合道 L6、道果进度 >=500 | 60 分钟 / 20 体力、`item.dao_fruit_fragment` 2 | 合道试炼、道果线索；每个 UTC 日最多创建 1 次行程 |
| `tribulation.sky_terrace` | 从 `dao.origin_gate` 出发；渡劫 L3 | 30 分钟 / `item.tribulation_token` 1（移动通行凭证） | 三次天劫试炼；顺序固定。每次试炼另按 progression 合同消耗 1 张凭证 |
| `ascension.heaven_path` | `ascension_ready`、`item.ascension_certificate` | 90 分钟 / 凭证锁定不立即消耗 | 最终战与飞升/留界入口；单实例 1 发起者 + 最多 4 协助者 |
| `ascension.left_world_hall` | `remained_in_world`，从飞升路出发 | 30 分钟 / 10 体力 | 道统建设、留界结局确认 |
| `location.final_arena` | 渡劫 L6、活动轮次开放 | 15 分钟 / 15 体力 | 终局天榜；不影响飞升资格 |

飞升路节点固定：`node.origin_gate -> node.heart_test -> node.dao_trial -> node.ascension_choice`。每节点限时 15 分钟，节点失败返回道源门并按 progression v0.6 增加天劫债；已领取普通节点奖励不回收，但最终资格不前进。飞升路同一时刻一个发起者实例，协助者只能加入同一 `battle_id`，不获得发起者境界/结局。

道源门行程复用服务端移动会话：创建时原子扣除体力与道果碎片，超时按已冻结路线结算；当日额度按 UTC 日期和行程开始时间计算，失败或重复请求不得返还额度或重复扣费。天劫台行程从道源门出发，创建时原子扣除 1 张天劫凭证，30 分钟后结算到达；渡劫 L3 是进入天劫台的最低境界。试炼只能在天劫台启动，且每次试炼启动仍单独扣除 progression 合同规定的凭证。

当前运行时只实现飞升路/留界殿的移动基础：飞升候选角色可从天劫台创建飞升路行程，
飞升凭证在抵达时扣除；留界角色可从飞升路前往留界殿。最终战会话、协助者加入、
`location.final_arena` 和真实玩家的 `ascension_ready` 生产路径仍未开放，因此这些地点
不能通过测试夹具状态之外的命令完成终局。

最终战成功后将位置冻结为 `ascension.heaven_path`，只允许 `ascension.choose_ending`；失败等待 7 天，不可排队。留界殿结局选择要求已锁定道果；飞升路选择要求最终战成功。关闭 v0.6 后不新建终局会话，已有候选角色仍可选择一次结局。

错误：`DAO_ORIGIN_REQUIREMENT_MISSING`、`TRIBULATION_TERRACE_REQUIREMENT_MISSING`、`TRIBULATION_LOCATION_REQUIRED`、`TRIAL_SEQUENCE_INVALID`、`ASCENSION_REQUIREMENT_MISSING`、`ASCENSION_INSTANCE_BUSY`、`ASCENSION_COOLDOWN`、`ENDING_STATE_REQUIRED`、`TRAVEL_PASS_INSUFFICIENT`、`SEASON_NOT_ACTIVE`。验收：节点顺序不可跳过；凭证锁定恢复安全；飞升凭证抵达时原子扣除；抵达凭证不足不改变位置或会话；协助者人数限制；失败不双加天劫债；终局关闭不丢失候选角色结局入口。
