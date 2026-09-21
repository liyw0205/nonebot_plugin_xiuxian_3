# 扩展：数据内容域

数据内容域负责规则包、内容包、schema、加载校验、发布、迁移和回滚。

完整内容规格以[完整内容开发总表](../../content-development.md)为准。此目录中的
`content-v*.md` 是发布快照：它们记录某个版本的稳定键和开放状态，不再与总表并列
定义开发顺序或玩法规则。

- [内容包](content-package.md)
- [校验与发布](validation-release.md)
- [数据库迁移](migrations.md)
- [用例与验收](use-cases.md)

所有 `content-v0.1.md` 至 `content-v0.6.md` 都必须遵守
[版本内容开发合同](../../content-development-contract.md)，并在提交前执行 JSON 格式校验和项目测试：

```bash
find data -name '*.json' -print0 | xargs -0 -n1 python3 -m json.tool >/dev/null
python3 -m pytest -q
```

这些检查是发布前的最低门槛；实际内容发布还必须执行引用闭合检查、dry-run、创建备份、
原子激活和激活后 health/read-only smoke。内容包只允许增加稳定键或显式关闭内容，不能
重写已结算 operation 引用的历史定义。
