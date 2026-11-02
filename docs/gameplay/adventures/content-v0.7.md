# v0.7 冒险内容基线：时序残响与祖灵支脉

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.7`，`rule_version=adventures-0.7.0`。本版只扩展现有通用秘境运行时，不新增数据库表、命令、物品、地点、图鉴或终局入口。

## 1. 新增秘境

| 稳定键 | 名称 / 别名 | 准入 | 路线与成本 | 次数 | 首通 | 再入 |
|:--|:--|:--|:--|:--|:--|:--|
| `instance.secret_realm.time_garden_echo` | 时序残响 / 时园残响、时序回声 | 炼虚 L1，位于 `cave.time_garden` | 4 节点 `resource → encounter → choice → encounter`；体力 25，无门票；60 分钟过期 | 每 UTC 周 1 次 | 时痕草 ×2、灵石 200 | 2/3 概率时痕草 ×1，1/3 无所得 |
| `instance.secret_realm.ancestral_vein` | 祖灵支脉 / 祖灵湖支脉、祖灵回声 | 化神 L1，位于 `beast.ancestral_lake` | 4 节点 `resource → encounter → choice → encounter`；体力 30，无门票；60 分钟过期 | 每 UTC 周 1 次 | 兽血 ×2、三界贸易口名望 8、灵石 150 | 2/3 概率兽血 ×1，1/3 无所得 |

两条记录均为 `record_type=common`，由 `secret_realm_rules` 的内容校验器解析；奖励物品均为来源闭合材料（时痕草来自 `explore.time_garden`，兽血来自 `explore.beast_hunt`），地方名望键可被 `local_reputation_maximum` 解析。祖灵支脉只读取境界与地点，不要求祖灵殿的妖界声望 3000 或血脉稳定 5000 bp；它是祖灵湖的外围支脉，不写 `story.ancestral_hall`。

## 2. 运行时合同

- 入口：`进入秘境 时序残响` / `进入秘境 祖灵支脉`；别名与中文名由 `resolve_secret_realm` 解析。
- 路线：四节点固定顺序，资源节点只前进；每个遭遇节点启动一场服务端自动战，战斗胜利后继续，战败使本次运行 `failed`，不发放首通或再入奖励。
- 失败与过期：失败只返还未消费门票（本版两条均无门票），保留体力消耗与本周次数；过期返还门票和锁定体力。两条记录均无门票，因此失败不返体力、过期返还全部体力。
- 奖励：首通按首通表发放，重复成功按 `repeat_reward_pool` 使用运行种子抽取一次并冻结；结算回放不重抽。地方名望按共享角色状态事务封顶，回复只显示实得。
- 次数：按 UTC 自然周计次，同角色同一时间只能有一处进行中的秘境；已有运行、长时行动、地点、境界、体力、门票或周期次数任一不满足时拒绝新建且零写。
- 持久化：沿用 `secret_realm_runs` 与 operation 账本；重启或 QQ/OneBot 身份切换后可从当前节点继续，结算 operation 重放返回原结果。
- 不写修为、突破、道果、天劫债、飞升资源、终局状态或战斗属性；不新增图鉴/故事旗标。

## 3. 指令、预览与帮助

- `秘境预览` 列出当前全部通用秘境，并标记每个秘境「可进入」或具体缺失原因（不在入口、境界不足、体力不足、缺少凭证、周期次数已用尽、已有进行中的秘境/长时行动）。
- 可进入的秘境在列表行末附蓝字「进入」，载荷为 `进入秘境 <中文名>`；不可进入的秘境不附入口链接。
- `秘境预览 <秘境名>` 只显示该通用秘境的详情，可进入时附一个完整动作按钮「进入此秘境」，不再重复同一动作的蓝字链接；不可进入时只显示缺失原因。
- `修仙帮助 探索` 在探索模式之后追加数据驱动的「当前开放秘境」列表，七条通用秘境均带 `进入秘境 <中文名>` 蓝字预填，帮助页本身不带按钮。
- QQ 官方使用原生 Markdown 链接与单个按钮；OneBot V11 或未声明 keyboard 能力的 AppID 走纯文本降级：链接渲染为「秘境名（进入秘境 秘境名）」，按钮渲染为「可发送：进入秘境 秘境名」，不保留 `command:`，不暴露稳定键。
- 专用秘境（祖灵殿、虚空遗迹、时序堡垒、道源、天劫回音、界隙裂隙、魔界深渊、遗府）继续使用各自命令与预览说明；`秘境预览 <专用秘境名>` 返回 `SECRET_REALM_NOT_FOUND`，不改变其既有入口。

## 4. 内容校验与迁移

- 加载器拒绝未知/未开放境界、未开放地点、未开放敌人、未开放奖励物品、无效地方名望、重复名称/别名、非法节点、空奖励池和非法次数/时长。
- `data/冒险/秘境.json` 为官方种子；`scripts/seed_migrations.json` 登记上一版 blob `166354ed…`（provenance `2c3c710…`）与本版 `a886eea…`，旧宿主按迁移守卫升级，用户自定义/未知种子保留。
- 反向助手以 `test/fixtures/official_seeds/common_secret_realms.json` 归档上一版完整 blob，断言其 SHA 属于已登记旧指纹；不通过删除当前记录重建，避免手写格式差异。

## 5. 验收

- `test/test_secret_realm_expansion.py`：内容合同/来源闭合、未知引用拒绝、预览可进入标记/蓝字/单按钮/OneBot 降级、探索帮助列表、时序残响首通/周限/重复池/过期退款、祖灵支脉首通/重启续跑/幂等/重复池。
- 既有通用秘境回归：`test_secret_realm_ironwood.py`、`test_secret_realm_intro.py`、`test_secret_realm_reward_settlement.py`、`test_secret_realm_upper.py`、`test_secret_realm_content.py`、`test_secret_realm_instance_content.py`。
- `test_help.py`、`test_explore_help_rendering.py`、`test_documentation.py`、`test_seed_migration.py -k "reverse or manifest"`。
