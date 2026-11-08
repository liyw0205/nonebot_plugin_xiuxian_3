# v0.10 生活内容基线（解锁商路、分阶派遣与解锁闲居）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.10`。

本版把三处"只解析不消费"的字段接上真实门槛，并为图鉴解锁补上生活侧消费者。

## 1. 商路解锁（`route_rules.RouteDefinition.unlock_key`）

| 路线 | 起讫 | 门槛 | 参数 |
|:--|:--|:--|:--|
| `route.town_herb_vale`（百草运输） | `xuantian.new_town` → `xuantian.herb_vale` | `hint.herb_route` | 3 体力、900 秒、每日 2、延误 1000 bp/600 秒、灵石 18 + 青石镇名望 3、货值上限 120 |
| `route.cloud_to_abyss_gate`（深渊商路） | `xuantian.cloud_city` → `demon.abyss_gate` | `encyclopedia.domain_tactics` | 6 体力、1800 秒、每日 1、延误 1500 bp/900 秒、灵石 45 + 云城名望 4、货值上限 200、仅 `cultivator` |

门槛读取 `codex_milestone_claims.unlocks_json`（与委托 `unlock_key` 同一来源）：未领取时
`开始运输` 返回 `ROUTE_UNLOCK_REQUIRED`、`运输预览` 的"当前缺少"列出"图鉴见闻"，均不扣任何资源。
`route.new_town_outskirts` 的 `unlock_key` 为空，行为不变。

## 2. 分阶派遣（`definition.required_stage`）

`_dispatch_preview` 原先硬编码"凡人以上"，从不读取已解析的 `required_stage`。现按
`_STAGE_ORDER` 比较声明档位（缺省 `mortal`，其序位等于原硬编码下限，故既有 16 条记录行为不变），
提示文案由 `_STAGE_REQUIREMENT_TEXT` 给出。

| 派遣 | 档位 | 参数 |
|:--|:--|:--|
| `dispatch.seeker.clinic_run`（寻道问诊） | `seeker` | 3600 秒、每日 2、2 体力、成功 8000/延误 1200/部分 800 |
| `dispatch.cultivator.herb_convoy`（入道后药圃督运） | `cultivator` | 5400 秒、每日 2、4 体力、成功 7000/延误 1200/部分 1200/失败 600，失败返还 2 体力 |

## 3. 解锁闲居（`requirements.codex_unlock`）

闲居路线新增可选 `requirements.codex_unlock`（校验 `codex_unlock` 存在，在 `_idle_preview`
以同一 claim 来源强制执行）。

| 闲居 | 档位 | 门槛 | 参数 |
|:--|:--|:--|:--|
| `idle.beast_observation`（观兽） | `seeker` | `display.codex_creature_badge` | 7200 秒、每日 1、1 体力 |
| `idle.tower_watch`（塔外守望） | `seeker` | `hint.tower_route` | 10800 秒、每日 1、2 体力 |

两条均带完整/逾时保底奖池（`reward_pool.idle.beast_observation[.fallback]`、
`reward_pool.idle.tower_watch[.fallback]`），奖励含既有 `codex.*` 见闻，由既有领取事务投影。
闲居路线 13 → 15，派遣 16 → 18。

## 4. 图鉴解锁的真实消费者

| 解锁 | 消费者 |
|:--|:--|
| `commission.town.extra_offer`、`commission.cloud_city.extra_order` | 城镇委托 `unlock_key` 门禁（既有） |
| `hint.herb_route` | `route.town_herb_vale`（本版） |
| `encyclopedia.domain_tactics` | `route.cloud_to_abyss_gate`（本版） |
| `display.codex_creature_badge` | `idle.beast_observation`（本版） |
| `hint.tower_route` | `idle.tower_watch`（本版） |
| `encyclopedia.paths_6`、`display.domain_observatory` | 图鉴概览「已解锁见闻」段与 `data.unlocked_benefits`（本版） |

## 边界

不新增命令、表或物品；不改既有路线/派遣/闲居的数值与门槛；未领取时一律拒绝且不扣资源，
领取后语义与幂等沿用既有实现。聚焦证据见 `test/test_transport_route_unlocks.py`、
`test/test_dispatch_stage_gate.py`、`test/test_codex_unlock_consumers.py`。
