# v0.1 道历与运营循环内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)与[道历与运营循环域](README.md)。`content_version=content-0.1`，`rule_version=routine-0.1.0`。

## 1. 道历问安、补录道历与灵木聚财

当前首版已实现本节运营命令、道契测试凭证和称号/功业录的事务与幂等审计；后续章节是完整开发合同，
不代表全部功能已经开放。

| 稳定键 | 开放/次数 | 成本 | 奖励 | 唯一键/失败 |
|:--|:--|:--|:--|:--|
| `ritual.checkin.daily` | 所有 active 角色；每业务日 1 次 | 无 | 灵石 20、精力 3；连续 7 日额外 `item.ticket.fate_basic` 1 | `daily:date:player`；重复回放 |
| `ritual.makeup.daily` | 当月漏签，最多补 2 次/月 | 灵石 30/次；每次只能补最近 3 日 | 原日奖励的 80%，不补连续天数；失败不扣 | `makeup:date:player`；已补/窗口外拒绝 |
| `ritual.spirit_tree.water` | 每角色 1 棵灵木；每日 1 次 | 精力 2 | `tree_water=1`；第 7 次可收获 | `tree:date:player`；重复不扣 |
| `ritual.spirit_tree.harvest` | 灵木水分 7/7 | 无；每周期一次 | 灵石 80–120、地方名望 +2、`item.seed.spirit_tree` 1（30%） | `tree_cycle:player`；收获后进入 24h cooldown |

灵木聚财收益池 `tree.harvest.v0.1` 权重为灵石 80/100/120 = 25/50/25；灵木不能被交易、重复种植或兑换修为。运营奖励不得发放修为或突破物；漏签补录只补奖励，不恢复连续签到。

## 2. 日/周/月道契

道契由 `billing.receipt` 验签后激活，核心不接触支付秘密；未验证凭证不得发放权益。
测试切片使用 Ed25519 签名的 `base64url(payload).base64url(signature)` 凭证，配置
`XIUXIAN3_BILLING_PUBLIC_KEY` 只保存公钥。凭证必须绑定 `subject=<adapter>:<platform_user_id>`、
商品键、金额、凭证号和签发时间；凭证摘要和权益快照进入数据库，明文凭证与私钥不进入核心。

| `contract_key` | 周期/价格基线 | 每日权益 | 周期权益 |
|:--|:--|:--|:--|
| `dao_contract.daily` | 1 日 / 30 灵石等价凭证 | 灵石 30、精力 2 | 激活日一次 |
| `dao_contract.weekly` | 7 日 / 180 灵石等价凭证 | 灵石 35、精力 3 | 激活即 `item.ticket.fate_basic` 2 |
| `dao_contract.monthly` | 30 日 / 600 灵石等价凭证 | 灵石 40、精力 4 | 激活即道号展示框 1；每 7 日名望 +3 |

同一商品同一周期不得叠加；续期从当前结束时间顺延。撤销只停止未结算未来权益，已领取不回收；外部验证失败不改变 entitlement。
用户可发送 `我的道契` 查询，发送 `激活道契 <凭证>` 激活，发送 `领取道契 日/周/月` 领取当日权益。
同一道契同一业务日唯一领取；月道契每 7 日追加地方名望 +3。道契不得增加修为、境界或突破准备度。

## 3. 机缘寻宝、问道行卷与功业录

- `gacha.fate.basic`：单抽 50 灵石或 `item.ticket.fate_basic` 1；十连 450 灵石，必须至少出现 1 个灵品/功法线索。池：灵石返还、药材、生产材料、道号碎片、配方线索；不放突破物/终局资产。保底计数 10 抽，保底状态按玩家/池保存。
- `pass.wayfaring.v0.1`：30 级，业务周期 28 日；每日任务上限 100 行卷点，周任务上限 500。免费线奖励材料/名望/道号展示；付费线需已验证 `dao_contract.monthly`，只增加展示、配方线索、灵木水分券，不给修为/突破物。
- `honor.title.*`：`title.first_seeking`、`title.town_helper`、`title.first_tower_clear`；纯展示，装备一个、备选保存不限。
- `honor.achievement.*`：`achievement.first_checkin`、`achievement.first_dispatch`、`achievement.first_craft`、`achievement.codex_5`、`achievement.tower_10`；完成奖励为道号、名望或图鉴页，领取唯一。

## 4. 七日入道与机缘密令

`quest.seven_day.v0.1` 按首次 `start_seeking` 起算 7 个业务日：D1 道历问安，D2 采集，D3 生产预览，D4 悬赏，D5 塔层 1，D6 派遣，D7 选择道途。每日目标可补做但不可跨日重置；完成奖励分别为材料/灵石/名望，D7 额外 `item.ticket.fate_basic` 2。

当前实现的目标键、基础奖励和状态如下：

| 日数 | 目标键 | 基础奖励 | 当前状态 |
|:--|:--|:--|:--|
| D1 | `quest.seven_day.day1_checkin` | 粗糙灵米 ×1 | 已开放 |
| D2 | `quest.seven_day.day2_gather` | 止血草 ×2 | 已开放 |
| D3 | `quest.seven_day.day3_production_preview` | 灵石 ×30 | 已开放；以生产预览或已开始订单作为可审计来源 |
| D4 | `quest.seven_day.day4_bounty` | 地方名望 +2 | 已开放；以接取悬赏作为可审计来源 |
| D5 | `quest.seven_day.day5_tower` | 阵砂 ×2 | 未开放；等待试炼塔/战斗运行时 |
| D6 | `quest.seven_day.day6_dispatch` | 灵石 ×50 | 未开放；等待派遣系统 |
| D7 | `quest.seven_day.day7_path` | 地方名望 +5、机缘签 ×2 | 已开放；以选择道途作为可审计来源 |

用户发送 `七日入道` 查看状态，发送 `领取七日目标 <1-7>` 领取已完成目标。目标起点、
目标日期、来源 operation、奖励和版本均持久化；同一日数或同一 operation 重试只回放原结果，
不同 operation 不能重复占用同一来源事件。D5/D6 在依赖关闭期间返回未完成，不创建战斗或派遣
会话。

称号与功业录当前开放以下来源：

| 稳定键 | 来源 | 奖励/状态 |
|:--|:--|:--|
| `title.first_seeking` | 首次寻仙问道 | 自动获得，可佩戴 |
| `title.town_helper` | 累计三次道历问安 | 自动获得，可佩戴 |
| `achievement.first_checkin` | 首次道历问安 | 地方名望 +3，可领取一次 |
| `achievement.first_craft` | 首次完成生产订单 | 服务信誉 +2，可领取一次 |
| `achievement.first_dispatch`、`achievement.codex_5`、`achievement.tower_10` | 派遣/图鉴/试炼塔 | 内容未开放，不可领取 |

发送 `功业录` 查看功业与称号，发送 `领取功业 序号` 领取奖励，发送 `佩戴称号 序号`
更换展示称号。称号是展示记录，不提供永久战斗属性；来源 operation、奖励版本和领取
operation 均持久化，重复请求只回放原结果。

`redemption.code` 支持 `code.onboarding.v0.1`、`code.repair.v0.1` 两个示例族；密令由
`XIUXIAN3_REDEMPTION_CODES` 配置注入，不写入文档明文密钥，数据库只保存密令哈希。每个
code 默认总库存 1000、每角色一次、可配置业务有效期和撤销状态；领取 operation 使用
密令哈希与角色身份派生的稳定键，数据库约束仍以 `code_key + player_id` 保证唯一。密令不得
发修为、突破物或道契权益。支持命令为 `兑换密令 <密令内容>`，成功后只展示奖励，不回显密令。

关闭：窗口结束后 pending 奖励保留 7 日；已激活道契按结束时间执行；灵木 running 周期按原池结算；密令关闭后拒绝新领。
