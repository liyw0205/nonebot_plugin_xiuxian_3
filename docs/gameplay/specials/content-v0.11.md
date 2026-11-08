# v0.11 特殊内容基线（道途分支的节拍数与来源次数对齐）

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.11`。

`story_rules` 原先只校验 `len(completed_nodes) >= required_source_count`，于是两个分支比自己的门槛
短一截：`sojourner`（闲居）要求 2 次闲居结算却只有 1 个分支节拍，`wanderer`（游历）要求 3 次战斗却只有
2 个节拍。校验宽松，所以内容一直能加载，只是在分支叙事上缺了最后一拍。

## 变更

| 分支 | 来源类型 | 要求次数 | 节拍（含入口节点之后） |
|:--|:--|:--|:--|
| `merchant` 商路 | commission | 3 | `node.merchant.1`–`.3` |
| `warden` 守望 | battle | 2 | `node.arrival` + `node.warden.1`–`.2` |
| `gardener` 药圃 | harvest_or_dispatch | 2 | `node.arrival` + `node.gardener.1`–`.2` |
| `wanderer` 游历 | battle | 3 | `node.arrival` + `node.wanderer.1`–`.3`（本版补第三拍） |
| `sojourner` 闲居 | idle_claims | 2 | `node.arrival` + `node.sojourner.1`–`.2`（本版补第二拍） |

## 规则

- 起点为故事入口节点（`node.arrival`）的分支：入口节点之后必须恰好是
  `node.<branch>.1` … `node.<branch>.<required_source_count>`。
- 不以入口节点起头的分支：整份列表必须恰好是这组节拍。
- 任何偏差抛 `StoryContentError`，不再接受"节拍不足但数量够"的记录。

未新增分支、来源类型、结局、旗标、图鉴条目或外观键；五个分支的 `ending_key`、`flag_key`、
`codex_entry_key`、`appearance_key` 与 `required_source_count` 均未改动。
聚焦证据见 `test/test_story_branch_beats.py`。
