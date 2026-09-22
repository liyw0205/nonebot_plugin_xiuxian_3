# v0.1 世界地点内容基线：玄天界起步区

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.1`
- `rule_version`：`world-0.1.0`
- 写用例：`world.preview_travel`、`world.start_travel`、`world.settle_travel`、`world.return_to_town`。
- 位置初始值：`player.create` 成功后为 `xuantian.new_town`；`new_user` 只能在此阅读、寻仙和开始引导。

## 1. 地点定义

| `location_key` | 世界 | 准入 | 单程耗时/成本 | 环境与可用动作 | 状态 |
|:--|:--|:--|:--|:--|:--|
| `xuantian.new_town` | 玄天界 | `new_user` 以上 | 0 / 0 | `training_bp=10000`；寻仙、任务、基础交易、拜访、返回 | `open` |
| `xuantian.outskirts` | 玄天界 | `mortal` 以上 | 30 秒 / 2 体力 | `risk=low`；教学采集、短历练、训练战 | `open` |
| `xuantian.sect_gate` | 玄天界 | 聚气 L4 或有效师徒邀请 | 1 分钟 / 3 体力 | `training_bp=10500`；入宗、宗门任务、功法咨询 | `open` |
| `xuantian.spirit_field` | 玄天界 | 感气 L2、完成 `guide.gather_blood_grass` | 90 秒 / 4 体力 | `training_bp=11500`；灵叶采集、灵泉修炼、教学生产 | `open` |
| `cave.mist_grotto` | 洞天 | 聚气 L4、持 `item.cave_pass_basic` | 2 分钟 / 5 体力、10 灵石、凭证 1 | `risk=medium`；洞天探索、灵田、炼丹 | `open` |
| `demon.abyss_gate` | 魔界 | 筑基 L6、`quest.demon_intro` | 2 分钟 / 10 体力 | 只展示魔界引导和入口条件 | `locked` |
| `beast.ten_thousand_hills` | 妖界 | 筑基 L6、`quest.beast_intro` | 2 分钟 / 10 体力 | 只展示妖界引导和入口条件 | `locked` |

`locked` 地点不得创建移动会话、扣体力或消耗凭证；查询只返回开放版本、缺失条件和叙事摘要。洞天凭证在移动会话成功创建后消耗，前置/容量/operation 冲突失败时解除锁定。

## 2. 移动会话

```text
preview -> created -> running -> arrived
                     -> cancelled (仅 created)
                     -> expired (任务恢复后结算)
```

`world.start_travel` 输入目标、移动方式、`operation_id`。预检查：地点 `open`、角色未暂停、无战斗/生产/突破/移动会话、准入满足、资源足够。通过后同一事务扣体力/灵石、锁凭证、创建 `TravelSession`；到达时写位置、消耗凭证并完成 operation。普通地点移动没有随机途中事件；洞天移动仅由后续探索会话触发事件。

`world.return_to_town` 从玄天界地点返回青石镇：耗时 30 秒、体力 1；洞天返回耗时 1 分钟、体力 2；不能绕过战斗/生产/突破锁。已关闭地点中的角色仍可执行该返回动作。

当前运行时的灵泉谷最小入口由 `前往灵泉谷` 提供：角色需处于感气二层或以上并完成
`guide.gather_blood_grass`，移动消耗 4 点体力，抵达后位置写入 `xuantian.spirit_field`。
该入口与正式 `world.start_travel` 会话共用准入和 operation 事务边界；当前只实现从新手城
或近郊教学位置进入灵泉谷的切片，完整世界移动会话仍按本合同逐步接入。准入失败不扣体力、
不改变位置。

## 3. 失败、关闭与验收

错误：`LOCATION_NOT_FOUND`、`LOCATION_LOCKED`、`LOCATION_REQUIREMENT_MISSING`、`TRAVEL_BUSY`、`TRAVEL_RESOURCE_INSUFFICIENT`、`PLAYER_OCCUPIED`、`TRAVEL_NOT_READY`。观测写起终点、成本、准入快照、会话状态、内容版本和耗时。

关闭 v0.1 地点时拒绝新会话，已运行会话按快照到达或用返回规则撤离；不得删除在场角色。验收：魔界/妖界入口不扣费；洞天失败入口不耗凭证；相同 operation 返回同一会话；到达重复结算不重复扣费/消耗凭证；暂停角色只能查询地点。
