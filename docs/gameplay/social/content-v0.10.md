# v0.10 留界据点建造进度

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.10`，
`rule_version=social-0.10.0`。本版把 `content-v0.8.md` 记录在案的后续项接上：留界据点建设不再
即时生效，而是进入可被留界线加速的建造进度。

## 1. 内容数据

`data/社交/道统据点.json` 的三个建设项新增 `build_hours`：

| 项目 | key | 世界功勋 | `build_hours` |
|:--|:--|--:|--:|
| 太清殿 | `project.dao_hall.main_hall` | 800 | 24 |
| 讲道台 | `project.dao_hall.lecture_hall` | 600 | 18 |
| 护界大阵 | `project.dao_hall.ward_array` | 1200 | 36 |

`dao_hall_content.py` 要求 `build_hours` 为 1–168 的整数，缺失或越界在任何写入前拒绝。

## 2. 建造流程

`建设据点 <项目名>` 仍按原前置校验（成员、重建期、未建成、前置项目、世界功勋），然后：

1. 在同一事务扣除世界功勋并写贡献账本；
2. 写入 `dao_hall_constructions`（`hall_id` 主键、项目、功勋、开始/完成时间、operation）；
3. 返回 `build_ends_at`；此时 `dao_hall_projects` 仍为空，项目效果不生效。

同一据点同时只能有一个建造中项目；重复开工返回 `DAO_HALL_CONSTRUCTION_BUSY`。
`据点`、`建立据点`、`加入据点`、`建设据点`、`维护据点`、`破坏据点` 等读写路径都会先执行
幂等完成器：`ends_at <= now` 时插入 `dao_hall_projects`、累加
`dao_halls.contributed_world_merit`、删除建造中记录。效果从该次读取/写入起生效。

建造中不阻塞维护、加入、退出与重建；重建期仍拒绝新开工。建造记录在进程重启后保留。

## 3. 留界线加速

`data/社交/道统路线.json` 的 `route.dao_settlement.remain` 带
`hall_construction_bonus_bp=1500`。据点读取玩家当前活跃宗门的 `dao_route_state`：

- 路线为留界时，建造秒数 = `build_hours * 3600 * 10000 // (10000 + 1500)`；
- 其他路线或未加入宗门时为 `build_hours * 3600`；
- 数值从路线内容读取，不在据点代码复制 1500。

24 小时太清殿在留界线下为 75130 秒（20:52:10），已用端到端测试钉住。
加成只影响新开工项目；开工时 `ends_at` 冻结，路线变更不重算。

## 4. 呈现与兼容

`据点` 状态页新增「建造中」行：项目名与完成时间；没有建造中项目时不显示。
`建设据点` 回执改为「已开工，预计 … 完成，到期后自动生效」，并显示当前核心席位上限
（项目尚未生效）。不新增玩家命令、按钮或帮助段。

- `dao_hall_projects` 结构不变；旧已建项目与旧存档不受影响。
- 新表由 schema 初始化补齐；建造中记录持久化。
- 扣功勋发生在开工事务；重复 operation 回放首次回执，不重复扣费。
- 建造期间功勋已扣但项目未生效，是明示的等待成本；成员、库房与已建项目不变。
- 路线加成不改变维护费、重建时长或项目效果数值。

## 5. 错误码

新增 `DAO_HALL_CONSTRUCTION_BUSY`；其余沿用 `DAO_HALL_PROJECT_BUILT`、
`DAO_HALL_PROJECT_LOCKED`、`DAO_HALL_MATERIAL_MISSING`、`DAO_HALL_REBUILDING`、
`DAO_HALL_NOT_FOUND`、`DAO_HALL_MEMBER_STATE`。

## 6. 验收

`test/test_dao_hall.py` 覆盖：

- 三个项目 `build_hours` 合同与缺失字段拒绝；
- 开工后项目未建成、功勋已扣、`build_ends_at` 存在；
- 同一据点重复开工返回 `DAO_HALL_CONSTRUCTION_BUSY`，不重复扣费；
- 推进 24h/18h 后读取据点自动完成，容量 30→35、维护费 5000→4500；
- 留界线 1500 bp 下 24h 项目为 75130 秒，20:52:10 后自动完成；
- 重启后建造中记录保留并可完成；
- 旧即时项目、operation 回放与既有据点行为不变。

官方种子迁移须登记旧/新指纹及真实 Git 来源，升级保留未知与自定义数据。
