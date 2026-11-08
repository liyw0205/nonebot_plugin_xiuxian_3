# v0.9 探索内容基线（线索图鉴与探索产出）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.9`。

## 1. 线索类物品的图鉴闭环

`record_material_discoveries` 以 `item.<域>.<后缀>` 映射到 `codex.material.<后缀>`。六个
`item.clue.*` 此前没有任何匹配条目，因此首次获得时投影静默失败；其中两条也没有公开产出。

| 线索 | 图鉴条目 | 公开产出 |
|:--|:--|:--|
| `item.clue.recipe_basic` | `codex.material.recipe_basic` | 机缘签 `reward.gacha.fate.basic` / `reward.gacha.fate.dao_echo` |
| `item.clue.manual_basic` | `codex.material.manual_basic` | 同上 |
| `item.clue.demon_contract` | `codex.material.demon_contract` | `reward_pool.exploration.demon_abyss` / `…abyss_depths` |
| `item.clue.demon_abyss_echo` | `codex.material.demon_abyss_echo` | `reward_pool.exploration.demon_abyss`（本版新增，权重 8） |
| `item.clue.beast_bloodline` | `codex.material.beast_bloodline` | `reward_pool.exploration.beast_hunt` |
| `item.clue.mist_cave_route` | `codex.material.mist_cave_route` | `reward_pool.exploration.mist_grotto`（本版新增，权重 9000） |

`data/来源/来源.json` 新增 `source.item.clues`，其 `channels` 只列真实产出线索的奖池/机缘签，
不再声明不产出线索的渠道。

## 2. 合同

- 线索仍为 `item_type=clue`、`bind_type=character_bound`、不可交易；本版只补图鉴条目与产出，
  不改物品属性、不改任何奖池的既有档位权重（仅追加一档）。
- 图鉴投影沿用既有 `record_material_discoveries`：首次获得写一行 `codex_entries`，重复获得只更新
  `last_seen_at`；不新增条目类型或分类。
- 旧宿主由 `scripts/seed_migrations.json` 的 `图鉴/条目.json`、`奖励/奖励.json`、`来源/来源.json`
  规则升级（旧 blob 指纹 + provenance）；自定义/未知种子仍按守卫保留。

## 边界

不新增物品、奖池类别、命令或表；不改既有探索模式的数值与门槛；不把未登记的线索产出写成公开来源。
聚焦证据见 `test/test_clue_codex_lifecycle.py`。
