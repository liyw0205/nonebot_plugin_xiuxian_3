# v0.6 灵兽与灵骑内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=companions-0.6.0`。

- `beast.evolution.dao`：阶段 III、道统服务材料 5；成功率 60%，失败休养 24h，等级上限 60。
- `mount.evolution.dao`：灵骑等级 40、留界鞍具 1；成功率 60%；公共运输耗时 -15%，耐力 100。
- `beast.gear.dao_service`、`mount.tack.dao_service`：只提供道统服务/建设/展示效果，不提供道果、功勋、飞升或天劫属性。

飞升角色的灵兽/灵骑实体转为终局历史只读；留界角色可以继续维护。任何灵兽/灵骑操作写终局状态或终局资源都拒绝并记录 `ENDGAME_ASSET_FORBIDDEN`。