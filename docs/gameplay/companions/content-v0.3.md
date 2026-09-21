# v0.3 灵兽与灵骑内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=companions-0.3.0`。

- `beast.evolution.realm`：灵兽等级 20、亲和 60、品种材料 2；成功率 90%，失败休养 2h；开启第 2 技能槽，等级上限 30。
- `mount.evolution.realm`：灵骑等级 10、跨界鞍具 1；成功率 90%，运输耗时 -8%、耐力 40；等级上限 15。
- `beast.gear.boundary_harness`：跨界采集负重 +15，不改变战斗伤害。
- `mount.tack.boundary_saddle`：跨界移动成本 -5%，耐久 2500。

跨界战斗读取灵兽/灵骑快照，不能在战斗中临时升级或换装；失败不降境界、不删实体，按血脉/污染规则进入休养或维护。