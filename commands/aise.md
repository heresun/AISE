---
description: AISE 过程增强审查机制 v2 - 端到端任务流程编排
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill, Agent, TaskCreate, TaskUpdate, EnterPlanMode, ExitPlanMode
---

# /aise — AISE 过程增强审查机制

## 用途

按 v2 设计图执行完整的增强审查工作流，覆盖 文档产出 → 用户对齐 → 任务分割（DAG）→ TDD 执行 → 客观验证（硬门禁）→ 多 persona 审查（软门禁）→ 智能熔断 → 知识沉淀 闭环。

## 输入约定

- `$ARGUMENTS` 描述本次要做的事情
- 若 `$ARGUMENTS` 为空，向用户询问任务目标

## 执行步骤

### 步骤 0：环境准备

1. 确认当前工作目录在项目根目录下
2. 若无 `.aise/` 目录，执行：
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_init.py"
   ```
3. 读取 `.aise/progress.md`，若有进行中的流程，询问用户继续或重启

### 步骤 1：文档产出

调用 **`aise-brainstorming`** skill 产出：
- `docs/works/prd/<task>.md` — 需求文档
- `.aise/plan.md` — 顶层计划

验收标准 AC 必须可直接对应到测试用例。

### 步骤 2：用户对齐 Checkpoint

1. 使用 `EnterPlanMode` 展示文档摘要和计划要点，等待用户 `ExitPlanMode` 批准
2. ExitPlanMode 后锁定 plan：
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_run_init.py" --project-root "$(pwd)" --task-title-override "$ARGUMENTS"
   ```

### 步骤 3：任务分割（DAG）

调用 **`aise-planning-with-files`** skill，产出：
- `.aise/plan.json` — 机器可读（schema 详见 `docs/plan-schema.md`）
- `.aise/plan.md` — 人类可读

`test_manifest.pipe` 支持：`go-test-json-to-junit` / `mvn-surefire` / `pytest-junitxml` / `jest-junit` / `cargo-test-junit` / `cargo-nextest-junit`

### 步骤 4：任务执行（TDD）

对每个任务：

1. 调用 **`aise-test-driven-development`** skill 完成 Red → Green → Refactor
2. 通过 `Agent` 工具派发独立子代理执行
3. **Scope Gate**：worker 完成后、commit 前执行：
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_scope_check.py" --project-root "$(pwd)" --task-id "T-001"
   ```

### 步骤 5：客观验证门禁（硬门禁）

调用 **`aise-verification-before-completion`** skill，并执行：
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py"
```

- 自动检测项目类型，运行测试、Lint、类型检查
- 产出经 sha256 + mtime 签收写入 `evidence.jsonl`
- 任一失败 → 返回步骤 4 重试
- 可选复核：`aise_verify.py --verify-evidence`

### 步骤 6：多 Persona 审查（软门禁）

调用 **`aise-ce-review`** skill。并行派发独立审查 SubAgent，合并去重结果。

### 步骤 7：智能熔断

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_fuse.py"
```

### 步骤 8：知识沉淀

- 调用 **`aise-ce-compound`** skill 提取经验
- 执行 `aise_sediment.py` 落 patterns

### 步骤 9：健康度报表

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_dashboard.py"
```

输出到 `~/Documents/reports/YYYY-MM-DD-aise-health.md`

## 错误处理

- 每步完成更新 `.aise/progress.md`，异常中断后可续跑
- Hook 阻断时按提示返回上一步
