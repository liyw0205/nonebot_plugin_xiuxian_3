# v0.4 道历与运营循环内容基线

本文件遵守[版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=routine-0.4.0`。领域运营新增“公约贡献”而非付费战斗能力。

| 系统 | 稳定键/准入 | 参数与结算 |
|:--|:--|:--|
| 灵木 | `ritual.spirit_tree.domain`：参与领域公共项目 | 28 日周期；每日维护 1 次；收获建设券 1–2、灵石 400–600、领域名望 +8 |
| 机缘寻宝 | `gacha.fate.domain`：化神 L1 或领域许可 | 单抽 300、十连 2700；只给领域服务图纸/展示/名望；保底 30 |
| 行卷 | `pass.wayfaring.domain` | 40 级；领域前线/重建任务计点；关闭后 pending 7 日 |
| 功业/道号 | `achievement.domain_rebuilder` | 完成 3 个公共项目得 `title.domain_rebuilder`、服务信誉 +10 |
| 道契 | `dao_contract.domain_monthly` | 日权益为维修券/精力/名望，不发领域能量或领域核心 |
| 七日目标 | `quest.seven_day.domain` | 领域观察、公共维护、塔层/竞技演练；结局给服务权限 |
| 密令 | `code.domain_recovery` | 仅普通重建材料/维护券；管理员撤销必须记录原因 |

所有领域奖励按 `player_id + domain_project + window` 唯一；内容关闭停止新增项目，已结算贡献仍可领奖。