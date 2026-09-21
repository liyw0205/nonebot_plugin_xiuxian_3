# v0.1 角色、新手与入道内容基线

本文件是角色域 `content-0.1` 的历史发布快照，遵守[版本内容开发合同](../../content-development-contract.md)。完整范围、首版边界和跨域依赖以[完整内容开发总表](../../content-development.md)为准；本文件只记录该快照的稳定键、数值、奖励和失败参数。若与总表冲突，先修总表，再生成新的快照。

`rule_version`：`player-onboarding-v0.1.0`
`content_version`：`content-0.1`

## 1. 首版玩家旅程

```text
new_user
  -> player.create
  -> new_user（仅身份映射、无游戏资产）
  -> player.start_seeking / 寻仙问道
  -> mortal（资质快照与新手资源）
  -> 完成三项引导
  -> seeker（可选择体系分支）
  -> player.enter_cultivation
  -> cultivator + path_selected（首要道途与入道奖励）
  -> 感气修炼、采集、生产或基础战斗
```

“寻仙问道”是一次性 application 用例和叙事仪式，不是一个可长期停留的角色阶段；完成仪式后稳定状态为 `mortal`。`seeker` 是已完成凡人引导、可以作出修行构筑选择的状态。任何跳过或逆序请求都返回 `PLAYER_STAGE_CONFLICT`，不扣资源、不改变状态。

## 2. 状态、准入和允许动作

| `stage_key` | 展示名 | 进入条件 | 允许动作 | 明确禁止 |
|:--|:--|:--|:--|:--|
| `new_user` | 新用户 | `player.create` 成功 | 查看世界观、帮助、隐私说明、开始寻仙 | 钱包、采集、战斗、生产、修炼、道途选择 |
| `mortal` | 凡人 | 寻仙问道结算成功 | 新手城拜访、打工、基础交易、教学采集、查看资质 | 功法修炼、高风险战斗、高阶地点、道途技能 |
| `seeker` | 求道者 | 三项引导均完成 | 选择六大道途、选择辅修方向、查看入道计划 | 突破、正式洞天、跨界内容 |
| `cultivator` | 修行者 | 入道和首要道途选择成功 | 感气修炼、基础战斗、采集、生产、道途技能 | 聚气以上内容、未开放地点/配方 |


`status=active` 与 `stage` 分离：`suspended` 是 `status_key`，不是阶段，不覆盖原 stage；恢复时回到原 stage。`deleted` 只由专门的数据删除流程使用，首版不提供普通玩家删除命令。`status_key=suspended` 时只允许资料/申诉读取，所有上表阶段的写动作均拒绝。

## 3. 创建角色：`player.create`

输入：`platform`、`platform_user_id`、场景、平台昵称（仅内部记录）、可选 `dao_name`、`operation_id`。

- 稳定 operation：由适配器事件 ID绑定 `player.create` 输入；相同事件重试回放原结果，缺少事件 ID时使用请求 ID。
- 成功：创建 `player_id`、`stage=new_user`、`status=active`、`location_key=xuantian.new_town`。
- `dao_name` 为空时展示为未命名；非空道号最多 7 个字且全局不可重复。
- 重复相同 operation：返回原 `player_id` 和原状态。
- 相同平台身份使用新 operation：返回已有玩家资料，不创建第二角色；这属于幂等成功，不新增资产或奖励。
- 不创建钱包余额、体力、精力、背包物品、资质或道途。

首版一名平台身份在一个世界只能有一个未删除角色；跨平台绑定和多角色是后续内容。

## 4. 寻仙问道：`player.start_seeking`

### 4.1 前置条件与输入

前置：`stage=new_user`、`status=active`、地点为 `xuantian.new_town`。输入为 `player_id`、初始灵根倾向选择、`operation_id`。灵根倾向只影响叙事、部分配方/术法标签和未来内容权重，不直接给伤害倍率。

可选灵根倾向：`metal`、`wood`、`water`、`fire`、`earth`。首版不开放稀有灵根直选；复合灵根作为后续内容池。

### 4.2 资质快照

`QualificationSnapshot` 使用 `qualification.v0.1` 随机池，保存实际六维、灵根倾向、随机种子或结果摘要、调整记录、生成 operation 与版本。六维范围均为 5–15，且总和恒为 60：

| 属性键 | 名称 | 影响 |
|:--|:--|:--|
| `body` | 体魄 | 气血、近战、负重 |
| `spirit` | 灵力 | 灵力、术法、护盾 |
| `insight` | 悟性 | 修炼、学习、生产学习 |
| `root` | 根骨 | 突破稳定、生命成长、抗性 |
| `agility` | 身法 | 先手、闪避、探索 |
| `fortune` | 气运 | 事件质量和掉落波动 |

生成算法必须在内容包中固定：先给每项 5 点，剩余 30 点以确定性随机顺序逐点分配，单项上限 15。玩家在快照确认前拥有一次 `player.swap_qualification_stats`：交换两项属性值，不改变总和、不重抽随机池；第二次请求返回 `QUALIFICATION_ADJUSTMENT_USED`。

### 4.3 成功奖励与失败

寻仙问道首次结算创建 `mortal`，并通过单一奖励 operation 发放：

| 资源/物品键 | 数量 | 目的 |
|:--|--:|:--|
| `currency.spirit_stone` | 100 | 第一次基础交易与移动 |
| `resource.stamina` | 30/30 | 探索与采集行动 |
| `resource.energy` | 30/30 | 生产和生活行动 |
| `item.food.coarse_spirit_rice` | 3 | 教学恢复物品 |
| `item.herb.blood_grass` | 3 | 教学药材 |

同时把 `quest.first_seeking` 标记为可领取；该任务单独领取时额外奖励灵石 100、粗糙灵米 3，领取 operation 只能成功一次。文档中所有“新手灵石”均按这两个独立 operation 计算，不能在实现中合并为隐式双发或漏发。

失败：内容包不可用、随机池校验失败或持久化错误时，角色保持 `new_user`，不创建资质、不发放奖励；记录 failed operation，可在修复后使用同一 operation 重试。已完成寻仙问道使用新 operation 再请求时返回 `SEEKING_ALREADY_DONE`，不重新随机或发奖。

## 5. 凡人引导：`player.complete_intro`

凡人要完成下列三项不可跳过但可任意顺序的教学目标，完成后自动进入 `seeker`：

| 引导键 | 动作 | 资源/失败 | 产出 |
|:--|:--|:--|:--|
| `guide.read_world` | 阅读三界与道途说明并确认 | 无消耗；重复返回已完成 | 了解玄天/魔/妖三界与洞天福地 |
| `guide.gather_blood_grass` | 在 `xuantian.outskirts` 完成一次教学采集 | 2 体力；采集失败返还 1 体力，不返还时间 | `item.herb.blood_grass` 1–2，固定 `gather.v0.1` 池 |
| `guide.choose_service` | 选择炼丹、炼器或布阵教学服务 | 2 精力；预览不消耗 | 对应教学配方/阵图/维护任务之一 |

引导中所有有资产结果的请求都要有 operation、内容版本、随机结果和流水。三项都完成时 `player.complete_intro` 写入 `stage=seeker`；重复结算不重复发放任何奖励。

## 6. 体系分支与入道：`player.enter_cultivation`

`seeker` 选择一个首要体系分支，选择成功即进入 `cultivator`、公共境界 `qi_sensing` L1（感气一层/入门）。首版选择免费且不可免费切换；首次选择不是随机抽取。层数、段位和后续跨境规则以 [境界十层与段位规范](../progression/layers.md) 为准。

| `path_key` | 展示 | 初始动作 | 首版限制/状态 |
|:--|:--|:--|:--|
| `body` | 体修 | `skill.body.heavy_strike` | `battle_spirit=0`，保命判定需战意 100 |
| `spell` | 法修 | `skill.spell.water_bolt` | `mana` 与 1 回合施法冷却 |
| `device` | 器修 | `skill.device.scout_doll` | 机关操控上限 1，法器耐久 |
| `demonic` | 魔修 | `skill.demonic.pain_exchange` | 每次 +12 侵蚀；首版有净化教学 |
| `beast` | 妖修 | `skill.beast.partial_transform` | 每次 -5 化形稳定度 |
| `support` | 辅修 | `skill.support.quick_assessment` | 必须同时选择一项主辅修，额外消耗 2 精力 |

`support` 不是弱化战斗的“副职业占位”。它是首要构筑分支，必须同时选择 `alchemy`（炼丹）、`artifice`（炼器）或 `formation`（布阵）之一，作为 `subprofession_key`；子类生活玩法在后续引导/委托中解锁。体/法/器/魔/妖五条首要道途的主辅修默认未选择，在感气阶段完成一项生产教学后才能选择，避免首版一次性塞入所有界面。

入道奖励由 `player.enter_cultivation` 的单一 operation 发放：灵石 200、`item.manual.basic_qi` 1、对应道途试用技能 1。器修额外获得 `item.tool.basic_hammer`；辅修依主辅修获得 `item.tool.basic_furnace`、`item.tool.basic_hammer` 或 `item.mat.array_sand` 3。奖励定义引用 `foundation/items/content-v0.1.md`，不能由命令层硬编码。

失败规则：无效 path/subprofession、非 `seeker`、被暂停、内容未开放或 operation 输入冲突均不改变角色、道途、境界或奖励。道途切换首版只允许筑基后使用 `item.token.change_path` 与灵石 500；该 token 首版不掉落，仅用于测试与管理员受控恢复。

## 7. 首版资料卡与命令协议

首版公开的产品命令是修仙3新协议，不从旧项目继承：

| 命令/按钮意图 | application 用例 | 写入 | 说明 |
|:--|:--|:--|:--|
| `开始修仙` | `player.create` | 有 | 创建最小身份；可改为平台欢迎按钮 |
| `开始修仙 <道号>` | `player.create` | 有 | 建角时直接取道号；道号最多 7 个字且不可重复 |
| `寻仙问道` | `player.start_seeking` | 有 | 生成/回放资质快照 |
| `修仙改名 <道号>` | `player.rename` | 有 | 未命名角色首次改名免费，之后需要改名卡 |
| `我的资质` | `player.get_qualification` | 无 | 展示六维、灵根和一次调整资格 |
| `完成引导` | `player.complete_intro` | 有 | 只完成当前可验证的引导项 |
| `选择道途 <path_key>` | `player.enter_cultivation` | 有 | 文本与按钮同用例 |
| `我的修仙信息` / `我的状态` | `player.get_profile` | 无 | 只读状态卡 |

命令名、别名和按钮 payload 在真正接入 NoneBot/QQ 前冻结为 manifest fixture；本文件仅定义意图与用例，不承诺上游旧命令兼容。

资料卡最低显示：道号、阶段、公共境界、当前层数（1–10）、派生段位（入门/稳固/圆满/混元）、境内/总修为、灵根、六维摘要、首要道途、主辅修、玄天界当前位置、灵石、体力、精力、当前引导和可执行下一步；不展示平台用户 ID。图片、Markdown 或键盘发送失败时退化为文本，不能改变角色或重放写 operation。

## 8. 观测、回滚与验收

每次写用例至少记录 `request_id`、`operation_id`、`player_id`、阶段前后值、规则/内容版本、随机池版本、奖励摘要和结果状态；不得记录完整平台凭据或第三方 token。

回滚顺序：停止角色域写入口 -> 导出/校验 operation 与玩家计数 -> 恢复切片前备份 -> 重新执行迁移完整性检查 -> 对已回放的 operation 做只读抽样。不得通过删除 operation ledger 修复重复奖励。

v0.1 必测样例：

1. 同一 `player.create` 重试返回相同玩家且不创建资产。
2. 同一寻仙 operation 回放相同资质与奖励；不同输入复用 operation 返回冲突。
3. 属性总和恒为 60、每项 5–15，调整仅能交换一次。
4. 凡人不能跳过三项引导进入 `seeker` 或选择道途。
5. `support` 没有有效主辅修时入道拒绝且不发奖励。
6. 文本命令与按钮调用相同 application 用例，重复按钮不重复发放。
7. `suspended` 可读取资料，但所有写用例拒绝且无资产变化。
8. 数据库异常回滚角色、资质、奖励和 operation 的 applied 状态；可重试请求不产生双发。
