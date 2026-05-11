# Multi-Persona Review 配置（AISE v2 优化②⑥）

## 必激活 Personas（Always-on）

| Persona | Subagent 类型 | 关注点 |
|---------|--------------|--------|
| Correctness | `compound-engineering:review:correctness-reviewer` | 边界条件、错误处理 |
| Maintainability | `compound-engineering:review:maintainability-reviewer` | 可读性、命名、重复代码 |
| Testing | `compound-engineering:review:testing-reviewer` | 测试覆盖、断言强度 |

## 条件激活 Personas

按 diff 内容自动激活：

| 触发条件 | Persona | Subagent 类型 |
|---------|---------|--------------|
| diff 涉及 auth/输入处理/敏感信息 | Security | `compound-engineering:review:security-reviewer` |
| diff 涉及循环/SQL/缓存/IO | Performance | `compound-engineering:review:performance-reviewer` |
| diff 涉及数据库迁移 | DataMigration | `compound-engineering:review:data-migrations-reviewer` |
| diff 涉及 API 路由/类型签名 | ApiContract | `compound-engineering:review:api-contract-reviewer` |
| 项目为 Rails | DhhRails / KieranRails | 相应 reviewer |
| 项目为 Python | KieranPython | `compound-engineering:review:kieran-python-reviewer` |
| 项目为 TypeScript | KieranTypeScript | `compound-engineering:review:kieran-typescript-reviewer` |

## Clean-room 隔离配置

- 所有 Persona 通过 `Agent` 工具派发，`isolation: worktree`
- 每个 Persona 的 prompt 仅包含：
  1. 原始需求文档摘要（不超过 500 字）
  2. 任务文档（`.aise/plan.md` 对应任务条目）
  3. 本次 diff（`git diff HEAD~1` 或工作区改动）
  4. 项目 `docs/spec/` 中相关规范
- 不传递历史对话上下文

## 汇总规则

由 `compound-engineering:ce-review` 主流程负责：
- 去重
- 按严重程度（high/medium/low）排序
- 同一文件同一行的相邻评论合并

## 通过标准

- 无 high 级别问题 → 通过
- 有 high 级别但全部已在熔断阈值前修复 → 通过
- 否则 → 不通过，返回执行阶段
