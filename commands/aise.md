---
description: AISE 过程增强审查机制 v2 - 端到端任务流程编排
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill, Agent, TaskCreate, TaskUpdate, EnterPlanMode, ExitPlanMode
---

# /aise — AISE 过程增强审查机制

## 用途

按 v2 设计图执行完整的增强审查工作流，覆盖文档产出 → 用户对齐 → 任务分割（DAG）→ TDD 执行 → 客观验证（硬门禁）→ 多 persona 审查（软门禁）→ 智能熔断 → 知识沉淀闭环。

本命令为 **aise 插件**自带，所有依赖 Skill 已内置（命名带 `aise-` 前缀），无需安装其他插件即可运行。

## 输入约定

- `$ARGUMENTS` 描述本次要做的事情，例如：`/aise 给 data-bank 增加批量导出功能`
- 若 `$ARGUMENTS` 为空，向用户询问任务目标

## 执行步骤

### 步骤 0：环境准备

1. 确认当前工作目录在某个项目根目录下（应包含 `pom.xml`/`package.json`/`pyproject.toml` 等）
2. 若项目根目录无 `.aise/` 目录，执行：
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_init.py"
   ```
3. 读取 `.aise/progress.md`，若已有进行中的流程，询问用户是否继续或重启

### 步骤 1：文档产出阶段（大模型职责）

调用 **`aise-brainstorming`** skill 与用户对齐目标，产出：
- `docs/works/prd/<task>.md` — 需求文档（含验收标准 AC）
- `.aise/plan.md` — 顶层计划

**产物要求**：每个验收标准 AC 必须是可执行可断言的（能直接对应到测试用例）

### 步骤 2：用户对齐 Checkpoint（优化⑧）

**强制进入 Plan Mode**：使用 `EnterPlanMode` 工具，展示文档摘要+计划要点，等待用户 `ExitPlanMode` 批准。

未获批准时不进入后续步骤。

### 步骤 3：任务分割阶段（DAG）（优化④）

调用 **`aise-planning-with-files`** skill，输出包含以下字段的 DAG：

```yaml
tasks:
  - id: T1
    description: ...
    depends_on: []
    critical_path: true
    parallel_group: A
    estimated_tokens: 5000
    acceptance_criteria: [AC1, AC2]
```

写入 `.aise/plan.md`。

### 步骤 4：任务执行阶段（小模型 + TDD）（优化③⑥⑨）

对每个并行组的每个任务：

1. **结构化上下文注入**：自动通过 SessionStart hook 调用 `aise_inject_context.py`，将以下内容注入：
   - 全局 `CLAUDE.md`
   - 项目 `MEMORY.md` 与相关 `docs/spec/` 片段
   - 命中关键词的 `.aise/patterns/` 与 `~/.claude/docs/patterns/`
   - 本任务 AC

2. **TDD 强制前置**：调用 **`aise-test-driven-development`** skill 完成 Red → Green → Refactor

3. **使用 SubAgent 隔离上下文**：通过 `Agent` 工具派发到独立子代理（`subagent_type: general-purpose` 或 `Explore`），加 `isolation: worktree` 避免污染

### 步骤 5：客观验证门禁（硬门禁）（优化①）

调用 **`aise-verification-before-completion`** skill，并强制执行：

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py"
```

脚本会：
- 自动检测项目类型（Maven/Gradle/npm/Python）
- 运行测试、Lint、类型检查
- 任一失败 → 退出码非 0 → 强制返回步骤 4 重试

### 步骤 6：多 Persona 审查（软门禁）（优化②⑥）

调用 **`aise-ce-review`** skill。

**Clean-room 配置**（写入 `.aise/review-config.md`）：
- 通过 `Agent` 工具派发并行 SubAgent，每个使用 `isolation: worktree`
- 每个审查者仅接收：原始需求摘要 + 任务文档 + diff（不传历史对话）
- 结果通过 `aise-ce-review` 的合并去重流程汇总

### 步骤 7：智能熔断判断（优化⑤）

执行：
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_fuse.py"
```

退出码：
- `0` → 通过，前进
- `2` → 熔断触发，停止并向用户报告原因
- `1` → 需要继续修复，但未触发熔断 → 返回步骤 4

### 步骤 8：知识沉淀闭环（优化⑦）

任务完成后：
- 调用 **`aise-ce-compound`** skill 提取本次踩坑/优解
- 执行 `aise_sediment.py`：把 patterns 落到 `.aise/patterns/` 与（高价值时）`~/.claude/docs/patterns/`
- 若有跨项目通用经验，提示用户更新 `~/.claude/CLAUDE.md`

### 步骤 9：生成本次健康度报表（优化⑩）

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_dashboard.py"
```

输出到 `~/Documents/reports/YYYY-MM-DD-aise-health.md`

## 错误处理

- 每个步骤完成立刻更新 `.aise/progress.md`
- 异常中断时下次 `/aise` 会读取 progress.md 询问是否续跑
- Hook 阻断时不要试图绕过，按提示返回上一步

## 注意事项

- 本命令是**编排器**，不直接写业务代码，所有动作均委托给插件自带 Skill 或 SubAgent
- 遵循 KISS：能复用 Skill 就不要重写
- 全程中文交流，焦小糖人设保持
- 所有 `aise-*` Skill 均为本插件自带的副本，无需依赖外部插件
