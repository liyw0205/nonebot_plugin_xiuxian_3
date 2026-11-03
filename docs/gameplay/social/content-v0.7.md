# v0.7 社交内容基线：留界据点

`docs/gameplay/social/content-v0.6.md` 已冻结 `settlement.dao_hall` 的准入、席位、维护与重建期，
`docs/gameplay/economy/content-v0.6.md` 冻结建设货币为世界功勋（不可灵石购买），但在此之前
仓内没有对应数据文件、加载器、表、用例或命令。本版把它做成可玩的单服社交结构。

## 数据合同

`data/社交/道统据点.json`（kind `dao_hall`）承接全部数值：

| 键 | 字段 | 值 | 来源 |
|:--|:--|:--|:--|
| `hall.dao_settlement.defaults` | `required_ending` | `remain_in_world` | social v0.6「留界结局」 |
| | `required_world_merit` | 2000 | social v0.6 |
| | `spirit_stones` | 5000（**存入库房**，非消耗） | social v0.6 |
| | `core_capacity` | 30 | social v0.6 |
| | `maintenance_spirit_stones` | 5000 / 周 | social v0.6 |
| | `maintenance_period_days` | 7 | 本版按「周维护」明确 |
| | `rebuild_hours` | 72 | social v0.6 |
| | `core_required_realms` | `tribulation`、`dao_union` | social v0.6「核心成员必须渡劫或留界」 |

建设项（世界功勋结算，每项声明前置与固定效果集合）：

| 键 | 名称 | 功勋 | 前置 | 效果 |
|:--|:--|--:|:--|:--|
| `project.dao_hall.main_hall` | 太清殿 | 800 | — | 核心席位 +5 |
| `project.dao_hall.lecture_hall` | 讲道台 | 600 | 太清殿 | 周维护 -1000 bp（5000 → 4500） |
| `project.dao_hall.ward_array` | 护界大阵 | 1200 | 太清殿 | 重建期 72h → 48h |

数值理由：成立与维护沿用已冻结的 5000/2000/30/72，不另立第二套；三项建设按「先扩席位、再省维护、
最后缩短重建」排成一条前置链，使功勋有长期消耗去处而不引入新的资源种类；效果上限由加载器
（`core_capacity_bonus ≤ 30`、`maintenance_discount_bp ≤ 5000`、`rebuild_hours_reduction ≤ 48`）封顶，
避免后续内容把席位或折扣推到破坏平衡的量级。

## 校验与迁移边界

`social/dao_hall_content.py` 校验：kind 与键前缀（`hall.` / `project.dao_hall.`）、字段集合、
`required_ending` 必须在 `endgame_endings` 的允许集合内、`core_required_realms` 必须是已登记境界、
正数与 1–720 区间的窗口、效果字段白名单与上限、项目前置存在且**无环**、别名唯一；非法抛
`ContentError` 并在导入期构建，部署校验同样失败。

`社交/道统据点.json` 是新增官方种子，`scripts/seed_migrations.json` 以空 `old_sha256` 登记
（此前不存在该官方文件，安装器按「缺失即安装」处理），新摘要随业务提交回填。四张新表
（`dao_halls`、`dao_hall_members`、`dao_hall_projects`、`dao_hall_contributions`）用
`CREATE TABLE IF NOT EXISTS`，旧库无需回填，也不需要迁移旧行。

## 运行时

- **成立**：单事务内校验留界结局、世界功勋 2000、灵石 5000、且未加入其他据点；扣功勋与灵石，
  灵石**计入库房**，创始人写为 `founder`。库房由此获得第一周的维护资金。
- **加入**：`dao_hall_members.player_id` 唯一，因此一人只能属于一个据点；达渡劫/合道或有留界结局者
  取 `core` 席位（受 `core_capacity` 与实际建设加成限制），否则只能作 `guest`，不占核心位。
- **退出**：创始者不可退出（`DAO_HALL_FOUNDER_LOCKED`），其他成员退出即释放席位。
- **建设**：校验前置、是否已建成、功勋是否足够；扣功勋、写 `dao_hall_projects`、累加
  `contributed_world_merit`，并按效果即时改变席位上限、维护费与重建时长。
- **维护**：到 `last_maintained_at + 7 天` 才可缴纳；先从库房支出，不足部分由经办成员自付，
  两段都写 `dao_hall_contributions` 账本；重建期内维护费为 0 但仍登记时间。
- **重建期**：`damage_dao_hall` 把据点置为 `rebuilding` 并写入 `rebuild_ends_at`（护界大阵缩短到 48h）。
  期间加入与建设被 `DAO_HALL_REBUILDING` 拒绝，成员、库房与已建项目全部保留；到期后任意读取
  或写入路径先做一次幂等恢复（回到 `active`、清空 `rebuild_ends_at`）。

全部写操作单事务 + `operations` 幂等：同一 operation 重放返回原结果，输入不一致抛
`OperationConflictError`（`LEDGER_CONFLICT`）。据点是单服结构，不涉及跨服匹配、身份合并或玩家间资产转移。

## 命令与呈现

`据点`（别名 `留界据点`、`道统据点`）、`建立据点`（别名 `开辟据点`）、`加入据点`、`退出据点`、
`建设据点 <项目名>`、`维护据点`。稳定错误码：`DAO_HALL_NOT_FOUND`、`DAO_HALL_ALREADY_JOINED`、
`DAO_HALL_REQUIREMENT`、`DAO_HALL_CAPACITY`、`DAO_HALL_REBUILDING`、`DAO_HALL_PROJECT_LOCKED`、
`DAO_HALL_PROJECT_BUILT`、`DAO_HALL_MATERIAL_MISSING`、`DAO_HALL_FOUNDER_LOCKED`、
`DAO_HALL_CORE_REQUIRED`、`DAO_HALL_MAINTENANCE_NOT_DUE`、`DAO_HALL_PROJECT_NOT_FOUND`、
`INVALID_DAO_HALL_COMMAND`、`LEDGER_CONFLICT`，失败一律零写。

QQ 原生 Markdown 下，据点页按当前状态只挂一个动作按钮（维护到期→「维护据点」、重建中→「查看据点」），
未成立时只给 `建立据点` 蓝字预填；OneBot 与纯文本降级为可读命令与「可发送：…」，不暴露稳定键。
`修仙帮助 社交` 追加由内容派生的据点段落，不含按钮网格。

## 与非目标的关系

据点**不**影响飞升资格、天劫债、道果进度与 `season.final_heaven` 三榜（留界榜本就不要求据点建设）。
`dao.choose_route`、`dao.council_vote`、`market.dao_fragment` 与据点战争仍未开放，本版只留下
`damage_dao_hall` 作为将来战争结算的入口，不新造战争规则。
