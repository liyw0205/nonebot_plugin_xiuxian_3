# v0.2 世界地点内容基线：玄天中层与魔界引导

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。

- `content_version`：`content-0.2`
- `rule_version`：`world-0.2.0`
- 新用例：`world.board_cloud_boat`、`world.accept_demon_intro`、`world.use_array_hall`。

| `location_key` | 准入 | 耗时/成本 | 环境与动作 | 关闭/失败 |
|:--|:--|:--|:--|:--|
| `xuantian.cloud_city` | 金丹 | 3 分钟 / 8 体力 | 高阶市场、炼器区、阵师会馆；`training_bp=11000` | 无云舟/移动状态拒绝 |
| `xuantian.cloud_mine` | 筑基、采矿子类等级 2 或矿区委托 | 2 分钟 / 6 体力 | 云铁采集、矿兽战；`risk=medium` | 工具/精力不足不能开始采集 |
| `xuantian.floating_boat` | 筑基、灵石 `>=500` | 1 分钟 / 500 灵石 | 云舟调度、洞天二层/魔界引导航线 | 金丹以下不能购买中层航线 |
| `cave.mist_grotto_2` | 金丹、`item.cave_pass_advanced` | 3 分钟 / 15 体力、凭证 1 | 金丹材料、精英战、灵田二层；`risk=high` | 凭证只在会话创建后消耗 |
| `xuantian.array_hall` | 聚气、宗门成员或阵法教学邀请 | 1 分钟 / 3 体力 | 布阵学习、阵材委托、领域前置 | 无权限只显示申请路径 |
| `demon.abyss_gate` | 筑基；抵达后才能执行 `quest.demon_intro` | 2 分钟 / 10 体力 | 魔界引导、契约风险教学；不开放核心区 | 引导完成前仅允许风险说明 |

## 云舟航线：`world.board_cloud_boat`

| `route_key` | 终点 | 前置 | 成本 | 时长 | 结果 |
|:--|:--|:--|:--|:--|:--|
| `route.cloud_to_mist2` | `cave.mist_grotto_2` | 金丹、凭证 | 500 灵石、8 体力 | 5 分钟 | 创建洞天二层到达会话 |
| `route.cloud_to_abyss_intro` | `demon.abyss_gate` | 筑基 | 500 灵石、10 体力 | 5 分钟 | 到达锁定入口，只可接引导 |
| `route.cloud_return` | `xuantian.cloud_city` | 位于任一云舟终点 | 200 灵石、3 体力 | 3 分钟 | 返回玄天城 |

云舟会话开始时扣费用、保存航线/资格/版本；取消仅限 `created` 且返还全部费用。`running` 后不能取消，超时 24 小时由恢复任务按原快照到达；云舟不随机失事，避免把移动费用变成不可控损失。

## 阵堂与魔界引导

阵堂的生产/学习不是地点自动效果：每个 `production` 或 `paths` 用例需再次校验宗门/邀请和订单成本；当前只开放 `recipe.array.mist_barrier`。`quest.demon_intro` 只提供魔界风险、污染与契约说明，完成后开放入口资格但不开放魔渊集市、战斗或掉落；魔界核心区相关动作返回 `CONTENT_CLOSED` 至 v0.3。

错误：`CLOUD_ROUTE_LOCKED`、`CLOUD_FARE_INSUFFICIENT`、`ARRAY_HALL_PERMISSION_DENIED`、`ADVANCED_CAVE_PASS_MISSING`。关闭 v0.2 时新航线/洞天二层停止，已运行航线按原版本结算。验收：云舟费用不因重试双扣；洞天二层凭证锁定正确；阵堂无权限不泄露生产结果；魔界引导不产生魔界资源。

## 当前运行时边界

本阶段开放云城/阵堂移动、三条云舟航线、抵达深渊门后的风险确认、阵堂权限检查，以及
`explore.cloud_mine`/`explore.cloud_boat_trial`/`explore.mist_grotto_2` 探索入口。矿区入口仍要求采矿标记或矿区许可，
云舟试炼要求位于云舟渡口且达到金丹 L1；洞天二层入口要求已经抵达该地点；`recipe.array.mist_barrier` 已开放预览、生产和结算，阵堂地点仍会再次校验宗门成员/教学邀请；v0.2 其它金丹配方、设施槽位维护、魔界核心区和魔界资源仍
返回关闭或未满足前置；已创建云舟按会话快照结算。`world.accept_demon_intro` 只写入入口资格和
`faction_reputation.demon=20`，不发魔核或妖血。
