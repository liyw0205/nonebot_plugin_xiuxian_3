# v0.3 道历与运营循环内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.3`，`rule_version=routine-0.3.0`。三界运营使用地区业务日和地区声望快照，不能用跨时区客户端日期。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 灵木 | `ritual.spirit_tree.realm`：三界许可或地区名望 500 | 21 日周期；可选玄天/魔界/妖界树种；收获灵石 260–380、对应地区名望 +6；失败只返种子 |
| 机缘寻宝 | `gacha.fate.three_realms`：元婴 L1 或三界许可 | 单抽 180、十连 1600；池含跨界配方线索/图鉴，不含神魂突破材料 |
| 行卷 | `pass.wayfaring.realm`：35 级、28 日 | 贡献来源增加跨界贸易/悬赏；赛季奖励只给道号、名望、故事旗标 |
| 功业 | `achievement.three_realms` | 三界各完成 5 项服务给 `title.three_realm_mediator`、世界志条目 |
| 道契 | `dao_contract.realm_monthly` | 30 日；每日灵石 80、精力 6、跨界服务展示 1 条；凭证签名必需 |
| 七日目标 | `quest.seven_day.realm` | 从首次三界许可起算；完成 7 日三界观察/贸易/派遣目标，奖励地区名望/图鉴 |
| 密令 | `code.realm_repair` | 总库存 300；只能发普通补给、运输券、图鉴线索 |

机缘池每个地区独立保底，地区池互不共享计数；抽取失败只损失本次投入，不产生负面战斗状态。