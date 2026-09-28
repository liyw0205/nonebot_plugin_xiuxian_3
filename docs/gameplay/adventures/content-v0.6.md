# v0.6 冒险内容基线：终局悬赏、道源秘境、天劫回音与飞升旁线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=adventures-0.6.0`。终局冒险只能读取终局资格，不能替代天劫试炼、最终战或结局选择。

| 类型 | 稳定键/准入 | 参数与奖励 |
|:--|:--|:--|
| 悬赏 | `bounty.dao_origin_service`：道统服务资格 | 完成公共服务 3；12h；道统名望 +20、故事图鉴 |
| 悬赏 | `bounty.ascension_supply`：普通角色也可参加 | 交付疗伤/维修物 5；8h；世界功勋 50、灵石 300；不得发飞升功勋 |
| 秘境 | `instance.secret_realm.dao_origin`：合道 L1、道源许可 | 单人 8 节点、60 体力/人；首通新篇章线索/展示；每角色 1 次 |
| 秘境 | `instance.secret_realm.heaven_echo`：渡劫 L1、非最终战 | 3 节点、天劫债不变；首通结局旁线旗标 |
| 主线 | `story.mainline.dao_echoes`：炼虚 L10 | 建设者/见证者/远行者三线各 10 关；lane 内顺序推进；只写故事/服务/图鉴旗标 |
| 斗法留影 | `combat.replay.v0.6` | 终局战日志永久保留但默认私有；公开只显示脱敏摘要和结局编号 |

禁止任何 `bounty`/`instance`/`mainline` operation 写 `ending_state`、道果、天劫债、飞升凭证、`resource.ascension_merit`。最终战与 `ascension.choose_ending` 仍是唯一终局写入口。

`story.mainline.dao_echoes` 的 `stage_key` 固定为 `lane.<builder|witness|traveler>.chapter.<01..10>`，内容版本为 `content-0.6`、规则版本为 `adventures-0.6.0`。`quest.dao_union` 的主线组件必须核验三个 lane 各自 10 个不同 stage 均为 `claimed`；其他 story（包括 `story.mainline.xuantian`）不能代替。旧主线记录保留作历史，不计入该资格。

玩家路径、逐关剧情摘要、图鉴旗标、顺序和幂等规则以[完整内容开发总表](../../content-development.md#542-三界回响主线)为准。运行命令：`道源主线`、`开始道源主线 <lane> <stage>`、`领取道源主线奖励 <lane> <stage>`。每关开始与领取分开记录；重复领取回放原 operation，重新挑战不再发图鉴旗标或资产。

#### 5.4.3 `instance.secret_realm.dao_origin`

道源秘境是合道角色的单人终局旁线，入口固定为 `dao.origin_gate`。角色须合道 L1、持有 `access.dao.origin`，入场原子扣除 60 体力；每个角色终身仅可尝试一次，运行时长 60 分钟。路线随机池为 `none`，固定八节点：`origin_threshold -> dao_spring -> three_realm_seal -> service_archive -> fruit_trace -> witness_platform -> origin_oath -> new_chapter_gate`。

路线推进由服务端按序校验，开始、节点、结算和系统补偿均写入 operation ledger；重启或 QQ/OneBot 身份切换后可从当前节点继续。跳跃节点、重复 operation 的不同输入、缺少地点/境界/许可、活动锁和一次性额度均原子拒绝。过期保留已扣体力和额度，不写首通结果；明确的系统中止才退还 60 体力并释放一次性额度。

首次完成在结算事务中写入 `story.dao_origin` 和 `codex.dao.service_origin`，不修改道果进度、天劫债、飞升凭证、`resource.ascension_merit` 或任何战斗资产。重复请求只回放原结算；验收见 `test/test_dao_origin_secret_realm_v06.py`。

#### 5.4.4 `instance.secret_realm.heaven_echo`

天劫回音是渡劫角色的单人结局旁线。角色达到渡劫 L1 且不在最终战进行中即可进入；没有地点、体力、票券或次数成本，允许在完成后重复挑战。运行时长固定 60 分钟，固定三节点：`heaven_threshold -> echo_corridor -> side_story_gate`。节点、结算和系统中止均写入独立 operation ledger，活动运行记录存于 `heaven_echo_runs`，不复用通用秘境表。

入口只读校验 `tribulation` 境界和最终战活动成员；任何拒绝均不创建运行记录。路线按序推进，重启或 QQ/OneBot V11 身份切换后可继续。过期只结束当前运行，不发旗标；明确的系统中止只结束运行，不退还资源（本合同无资源成本）。

首次成功结算在同一事务向 `intro_json.flags` 写入 `story.heaven_echo`，重复成功不重复写入。秘境操作禁止写 `ending_state`、`ending_key`、道果进度、`resource.ascension_merit`、天劫债、飞升凭证或最终战记录；`ascension.choose_ending` 仍是唯一结局选择写入口。验收见 `test/test_heaven_echo_secret_realm_v06.py`。
