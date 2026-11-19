# 有界性能验证

性能比较使用 `scripts/performance_benchmark.py` 自有的临时 SQLite，经过 QQ/OneBot
归一化、真实 application 调用与结果序列化；不连接玩家数据库。所有本地验证串行取得
`/tmp/nonebot-project-validation.lock`，使用共享开发解释器和 `timeout`。

本次整理移除十二份 2026-11-16 的独立测量报告；历史命令、原始数字及对应优化可从
Git 历史查询。旧环境的小样本数字不能作为当前代码或发布规模的性能保证。

## 当前比较入口

| 场景 | 参数 | 核对内容 |
|:--|:--|:--|
| 竞技场列表 | `--compare-arena-snapshot-list --command 竞技场列表` | 全局与按模式过期、非空候选、完整响应等价和索引约束 |
| 移动预览 | `--compare-travel-preview-projection --command '移动预览 玄天近郊'` | 重复与共用角色投影、完整响应等价、SQL 和阶段计数 |
| 虚空物资别名 | `--compare-void-material-item-cache --command '寄售物资 虚空晶体 1 100'` | 别名缓存、真实准入拒绝、报告返回及临时目录清理 |

每项比较在同一临时数据库交替运行两个实现，每个并发级别各测两次。显式指定小规模参数：

```bash
flock -w 600 /tmp/nonebot-project-validation.lock timeout 300s \
  /home/nonebot-shared-venv/bin/python scripts/performance_benchmark.py \
  --users 100 --batch-size 50 --requests 20 --concurrency 1 10 \
  --profile-sql --compare-arena-snapshot-list --command 竞技场列表
```

竞技场夹具固定时钟，包含两种公开模式及各自已过期/仍有效的快照，避免日期流逝后
仅比较空列表。查询计划核对实际检索列，不能依赖 SQLite 对等价索引的选择顺序。
移动预览与虚空别名比较复用既有解析及准入规则。

## 结果边界

定向回归检查响应、SQL、阶段计数及清理合同；耗时百分位用于观察，不把一次调度差异
当成功门槛。未启用 SQL profile 时标为未采集，不能当成零查询。RSS 是同进程高水位，
不是各变体独立峰值；同库最终大小也不是各变体独立占用。

本次不运行全量测试、十万或百万用户压力测试，也不以 SDK 模拟声称真实平台投递。
测试选择与已绿证据复用规则见[测试与验收](testing.md)。
