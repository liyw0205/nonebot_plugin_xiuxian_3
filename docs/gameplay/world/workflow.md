# 世界域：移动状态机

```text
travel: created -> running -> arrived
                    \-> interrupted/expired/failed
location: locked -> open -> closed
```

创建移动前检查地点、入口条件、角色战斗/生产/突破锁和资源。创建后先锁定费用，抵达结算才写入新位置和途中事件。

地点关闭不强制删除已在其中的角色；后续行动按撤离或封锁规则处理。重复到达结算只能写一次位置变更。