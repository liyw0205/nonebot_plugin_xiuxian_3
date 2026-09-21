# v0.6 常驻经营内容基线：道统服务、留界建设与新篇章物资

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.6`，`rule_version=livelihood-0.6.0`。终局不终止普通玩家的经营循环；飞升/留界角色提供道统服务和公共建设，但个人结局、道果与天劫资产不得通过经营转移、购买或代办。

## 1. 道统服务

| `service_key` | 发布/承接 | 内容 | 结算边界 |
|:--|:--|:--|:--|
| `dao_service.teach_craft` | 留界道统或信誉 >=60 服务者 | 指导一次生产/维护订单，订单质量预览 +300 bp | 不改变随机结果、不提高突破概率；每服务者/日 3 次 |
| `dao_service.shelter` | 道统设施 active | 提供休整/地块维护替代服务 | 每玩家/日 1 次，恢复体精/维护次数；不加修为 |
| `dao_service.newcomer_supply` | 道统公共箱 | 发放血草/灵米/基础材料包 | 每 `new_user`/赛季一次，全部绑定、无灵石/修为 |

留界角色可创建 `DaoServiceProject`，但项目资金/材料与其终局资产表隔离；飞升角色只能展示历史贡献，不能操作普通市场或公共仓库。所有服务按 `service_key + provider + recipient + business_date` 幂等。

## 2. 留界建设与新篇章准备

| `project_key` | 前置/贡献 | 完成效果 | 个人奖励 |
|:--|:--|:--|:--|
| `project.dao_settlement` | 任何活跃角色捐材料/服务；留界角色可加速 10 点/日 | 14 日内城镇委托库存 +30%、居所租金 -10% | 贡献 >=20：名望 +10、建设券 2 |
| `project.archive_library` | 交付已完成订单摘要/材料，不提交玩家隐私 | 解锁新篇章只读世界志与内容预览 | 贡献 >=10：信誉 +4 |
| `project.ascension_supply` | 天劫候选之外的角色可供给灵米/疗伤丹/维修 | 天劫相关常规服务库存 +20% | 贡献 >=15：运输券 2 |

建设项目不接收 `item.dao_fruit_fragment`、`item.tribulation_token`、`item.ascension_certificate`、终局装备或终局货币；这些输入一律 `ENDGAME_ASSET_FORBIDDEN`。项目成功不改变 `resource.dao_fruit_progress`、`resource.ascension_merit` 或结局状态。

## 3. 周期与关闭

道统服务按业务日、建设项目按 14 日轮次；轮次关闭后只结算已锁服务/贡献。若道统解散/留界角色不可用，服务站转 `inactive`，已预约休整/维护返还次数，不返还已完成服务结果。新篇章资格由内容发布/结局状态决定，经营项目只能提供预览和公共物资，不决定资格。

## 4. 验收

普通角色可参与三类留界建设；终局资产被拒绝作为经营输入；服务不产生修为/道果/飞升功勋；飞升角色不能重新进入普通市场；项目和服务重复 operation 不双给名望、券或物资。