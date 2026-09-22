# 目标架构

## 1. 依赖方向

```text
NoneBot / Web / CLI adapters
            |
       application use cases
            |
       domain rules + values
            |
          ports
            ^
 infrastructure implementations
```

领域层不能导入 NoneBot、Flask、APScheduler、SQLite、网络客户端或文件系统。
应用层编排用例和事务；适配器只负责解析输入、调用用例和呈现结果；基础设施
实现端口并提供观测、超时和资源边界。

## 2. 目标目录

```text
nonebot_plugin_xiuxian_3/
  src/xiuxian3/
    plugin.py                 # 唯一插件入口，只负责组合根
    bootstrap/                 # 生命周期、manifest 注册、健康检查
    domain/                    # 纯实体、值对象、规则、领域事件
    application/               # 一个公开方法对应一个业务动作
    ports/                     # 仓储、时钟、随机、消息、任务、配置协议
    infrastructure/            # SQLite、迁移、文件、网络、日志、任务实现
    adapters/
      nonebot/                 # 事件归一化、命令和按钮路由、消息投递
      web/                     # blueprint、DTO、认证、序列化
      cli/                     # 迁移、检查、备份和诊断命令
    features/<name>/           # manifest/application/domain/repository/tests
  migrations/
  docs/
  tests/
```

目录名不是强制 API；依赖检查和 import 边界才是强制约束。功能包不能通过
模块 import 副作用注册命令或任务，必须把声明返回给组合根统一激活。

当前 SQLite 实现采用渐进式拆分：`xiuxian/repository.py` 是稳定兼容门面，
`xiuxian/persistence/sqlite_repository.py` 负责连接、迁移、通用玩家映射和
尚未迁移的历史事务；领域事务通过 mixin 放在各域目录，例如
`progression/repository.py` 的资源恢复、`progression/endgame_repository.py` 的合道/渡劫试炼，
以及 `world/repository.py` 的虚空航道。
新领域写入口应优先落在对应域的 repository 模块，不再直接扩大兼容门面。

## 3. Feature manifest

每个功能 manifest 至少声明：稳定 feature id、显示名、命令/别名、权限、
配置开关、迁移版本、任务、Web 路由、所需端口、启动/关闭钩子和测试标签。
组合根负责检查：命令无冲突、迁移顺序明确、任务 ID 唯一、依赖已满足、关闭
功能后不会继续接受写请求。

## 4. 生命周期

启动顺序固定为：读取配置 → 创建路径与日志 → 打开数据库/执行迁移 → 构造
端口实现 → 注册 feature manifest → 注册命令/Web/任务 → 执行 readiness 检查。

关闭顺序固定为：停止接收新请求 → 等待关键资产任务 → 取消非关键任务 →
刷新操作/消息队列 → 关闭调度器和数据库 → 写入 shutdown 结果。

重复启动、热重载和测试进程不得重复注册 matcher、任务、后台线程或事件监听器。

## 5. 应用用例约束

- 用例输入/输出是可序列化 DTO 或领域结果，不接受 Event、Request、Message。
- 用例不主动发送消息；返回结果和可选的导航意图，由适配器呈现。
- 用例显式声明读/写、事务边界、幂等策略、错误类别和可重试性。
- 一个高风险资产动作只允许一个权威写路径；旧入口只能转发到该用例。

## 6. 观测

每个请求、操作、任务和消息发送至少带 `request_id`、`operation_id`（若有）、
feature、actor、scene 和结果状态。日志不得写 token、密码、完整 QQ 身份凭据
或未经脱敏的外部响应。指标至少覆盖成功/拒绝/失败、重试、队列丢弃、锁等待、
消息序号冲突、外部服务超时和迁移耗时。

## 7. 适配器复用边界

适配器兼容层可以复用上游 OneBot/QQ 的事件、消息段、引用回复、主动发送、
消息记录、撤回和路由索引经验，但只能转换为 xiuxian3 的
`CommandContext`、`ReplyPlan` 和能力结果，不能成为玩法规则仓库。

不复用上游命令、旧数据投影、旧数值、旧表结构或旧业务模块。任何 vendored 或
复用实现必须记录上游来源、版本、许可证、本地修改和回归结果，并隔离在 adapters
边界内。
