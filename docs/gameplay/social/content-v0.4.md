# v0.4 社交内容基线：领域宗门建设

本文件遵守 [版本内容开发合同](../../content-development-contract.md)。`content_version=content-0.4`，`rule_version=social-0.4.0`。宗门等级上限保持 5、成员上限保持 80、队伍上限保持 5；v0.4 新增领域建筑，不回退既有权限/容量。

| `building_key` | 前置/成本 | 建造/维护 | 效果与限制 |
|:--|:--|:--|:--|
| `building.domain_core` | 宗门等级 >=4、领域核心 2、灵石 10000 | 24h；每日维护 500 灵石 | 开放宗门主领域选择；无维护则 inactive |
| `building.domain_wall` | 等级 >=4、阵法 1、云铁 20、灵石 8000 | 24h；每日维护 300 | 宗门战防御 +1000 bp；同类不叠加 |
| `building.domain_garden` | 等级 >=4、古果 2、阵砂 10、灵石 6000 | 24h；每日维护 200 | 绑定宗门生产订单时间 -500 bp |

每宗门最多同时 `under_construction=2`、`active=3` 建筑；`domain_master` 职位可启动/维护/关闭建筑，但不能改成员职位、盟约或公共钱包权限。建造成本在会话创建时锁定，完成时消费；取消仅 `created` 阶段返还，processing 不可取消，超时由恢复任务结算。

化神导师任务：师傅化神、徒弟元婴、完成领域战协助 1 次；奖励徒弟 `domain_charge_max +10`（最多 150）、师傅 `merit` 100。每关系一次，不能通过更换师傅重复。

错误：`SECT_BUILDING_CAP`、`SECT_BUILDING_MAINTENANCE_UNPAID`、`DOMAIN_MASTER_PERMISSION_DENIED`、`MENTOR_REQUIREMENT_MISSING`。关闭后建筑只读/原维护结算，已建效果在维护到期后失效。验收：维护 job 不双扣；容量并发安全；领域花园不影响非宗门订单；导师奖励一次；领域职位不能越权。