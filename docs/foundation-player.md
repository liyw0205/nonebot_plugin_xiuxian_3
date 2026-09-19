# 基础：新手与角色

## 1. 目标

新玩家不应先面对复杂命令表，而应完成一条可理解的入道流程：认识世界、获得初始资质、选择方向、完成第一次行动并看到成长结果。

## 2. 身份状态

```text
new_user -> mortal -> seeker -> cultivator
                         -> path_selected
```

- `new_user`：只有平台身份映射，没有游戏资产。
- `mortal`：已完成寻仙问道，但未建立稳定修行循环。
- `seeker`：已经开始寻找功法、师承、资源或生活技能。
- `cultivator`：完成入道条件，可以使用公共修炼和突破系统。
- `path_selected`：已经选择首要道途；辅修可以稍后开启。
- `suspended`：被系统或管理员限制写入，读操作和申诉信息仍可用。

状态转换必须由应用用例完成，不能通过直接修改数据库字段跳过前置条件。

## 3. 新用户流程

### 3.1 第一次进入

系统创建平台身份映射、角色 ID、创建时间、场景偏好和最小状态。此时不发放大量灵石、装备或抽奖物品。

玩家可以查看：

- 世界观摘要。
- 隐私和数据说明。
- 入道流程说明。
- 当前可以执行的第一步。

### 3.2 寻仙问道

寻仙问道是一次性入门用例，生成 `QualificationSnapshot`：

- 灵根倾向：金、木、水、火、土及可扩展的复合倾向。
- 体魄：影响体修、气血和负重。
- 灵力：影响法修、法器和灵力上限。
- 悟性：影响学习、修炼和生产。
- 根骨：影响成长稳定、突破和抗性。
- 身法：影响先手、闪避和探索。
- 气运：影响事件质量和掉落波动，不直接提供固定战斗倍率。

随机结果采用可解释区间。首版可以提供一次有限调整机会，但调整必须有明确成本或引导条件。

### 3.3 凡人阶段

凡人可以：

- 采集基础资源和药材。
- 进行打工、交易、拜访和生活任务。
- 认识宗门、城市、地图和三界传说。
- 学习基础生活技能。
- 完成入道引导。

凡人不能使用完整功法、参加高风险战斗或进入高阶洞天福地。凡人阶段目标是让玩家理解世界并积累第一笔资源，而不是让玩家反复刷同一任务。

## 4. 角色资料

角色资料至少包括：

- 平台身份和角色 ID。
- 昵称、称号和头像偏好。
- 身份阶段、境界、当前层数（1–10）、派生段位和境内/总修为。
- 灵根、基础属性、道途和辅修。
- 当前世界、地点、宗门和阵营关系。
- 灵石、体力、精力、气血、灵力、材料和背包容量。
- 冷却、封禁、虚弱、污染、血脉和临时状态。
- 创建时间、最后行动时间和规则版本。

资料查询是只读操作，不应因为生成图片、状态卡或 Markdown 失败而改变角色状态。

## 5. 改名和重置

改名、重新选择道途和角色重置不是普通字段更新：

- 改名检查长度、敏感词、重复名和冷却。
- 道途重选需要剧情、资源或赛季规则许可，并保留历史记录。
- 重置必须明确哪些资产保留、哪些资产清空、是否影响排行和关系。
- 管理员重置必须记录操作者、原因、旧快照和新快照。

## 6. 首次奖励

首次奖励分为三类：

- 引导奖励：帮助玩家完成下一步，不提供长期碾压。
- 选择奖励：让玩家尝试不同道途或辅修。
- 里程碑奖励：完成入道、第一次修炼、第一次生产、第一次探索等。

奖励包必须有定义版本和领取记录。重复请求只返回原结果，不重复发放。

## 7. 异常路径

- 身份不存在：创建最小记录或返回明确的开始入口。
- 已完成寻仙问道：返回当前资质，不重新随机。
- 角色被暂停：允许查看原因和帮助，不允许资产写入。
- 引导步骤跳跃：返回当前步骤和可执行动作。
- 重复按钮：按 operation ID 返回原结果。
- 数据损坏：阻止继续写入，记录诊断信息，交给恢复流程。

## 8. 首版范围

首版实现新用户、寻仙问道、凡人、资质快照、入道、基础状态卡、首次奖励和第一次修炼。头像渲染、复杂称号、转生和多角色暂不作为首版依赖。

## 9. 实现合同

### 9.1 持久化字段

`Player` 至少保存：

| 字段 | 类型/约束 | 说明 |
|:--|:--|:--|
| `player_id` | 稳定字符串，唯一 | 游戏角色 ID |
| `platform` | 枚举 | `onebot_v11`、`qq`、`channel` 等 |
| `platform_user_id` | 字符串 | 平台用户标识，原样保存 |
| `status` | 枚举 | 角色状态，不能用任意文本 |
| `stage` | 枚举 | `new_user`、`mortal`、`seeker`、`cultivator` |
| `name` | 1-24 个 Unicode 字符 | 展示名，需唯一策略 |
| `qualification_snapshot_id` | 可空外键 | 寻仙问道结果 |
| `path_key` | 可空内容键 | 首要道途 |
| `subprofession_key` | 可空内容键 | 主辅修 |
| `location_key` | 内容键 | 当前地点 |
| `created_at` / `updated_at` | UTC 时间 | 由 `Clock` 提供 |
| `rule_version` | 字符串 | 当前角色规则版本 |

资质快照单独保存属性值、灵根倾向、随机池版本、随机结果摘要和生成 operation ID；不能覆盖更新。

### 9.2 用例契约

| 用例 | 输入 | 成功输出 | 写入 |
|:--|:--|:--|:--|
| `create_player` | 平台、用户 ID、场景、`operation_id` | `player_id`、`stage=new_user` | 角色、operation |
| `start_seeking` | `player_id`、随机选择、`operation_id` | 资质快照、`stage=mortal` | 快照、角色、奖励流水 |
| `enter_cultivation` | 角色、入道选择、`operation_id` | `stage=cultivator`、引导任务 | 角色、道途状态、任务 |
| `get_profile` | 角色、展示格式 | 状态 DTO | 无资产写入 |
| `rename_player` | 新名称、`operation_id` | 新名称和冷却时间 | 名称历史、角色、流水 |

所有写用例输入必须包含 `operation_id`。输出至少包含 `status`、`player_id`、`rule_version`、`operation_id` 和可展示消息键。

### 9.3 状态机

```text
new_user --start_seeking--> mortal
mortal --complete_intro--> seeker
seeker --choose_path_and_enter--> cultivator
new_user/mortal/seeker/cultivator --admin_suspend--> suspended
suspended --admin_restore--> 原状态快照
```

非法迁移返回 `PLAYER_STAGE_CONFLICT`，不产生资产流水。`start_seeking` 重试返回第一次生成的快照；不同输入复用同一 operation ID 返回 `OPERATION_CONFLICT`。

### 9.4 错误码

`PLAYER_NOT_FOUND`、`PLAYER_ALREADY_EXISTS`、`PLAYER_STAGE_CONFLICT`、`PLAYER_SUSPENDED`、`NAME_INVALID`、`NAME_TAKEN`、`SEEKING_ALREADY_DONE`、`QUALIFICATION_NOT_FOUND`、`OPERATION_CONFLICT`。

错误响应包含 `code`、用户可读消息、是否可重试和 `operation_id`；拒绝类错误不能改变角色、物品、灵石或任务。

### 9.5 验收样例

1. 同一平台用户重复 `create_player` 返回同一 `player_id`，角色只存在一条。
2. 同一 `start_seeking` operation 重试返回相同资质快照，随机池和结果不变化。
3. 已完成寻仙问道的角色再次执行返回 `SEEKING_ALREADY_DONE`，不新增奖励。
4. 被暂停角色可以查询资料，但所有资产写入返回 `PLAYER_SUSPENDED`。
5. 改名失败时名称历史、角色名称和流水均不变化。
