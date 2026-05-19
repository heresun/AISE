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

**ExitPlanMode 后立即锁定 plan**（v1.1 + v3.3 架构）：

v1.1 方式（旧，仅 snapshot）：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_snapshot.py" create --task-title "$ARGUMENTS"
```

**v3.3 推荐方式（一步到位：plan 校验 + snapshot + run_id 分配 + run_context）**：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_run_init.py" \
    --project-root "$(pwd)" \
    --task-title-override "$ARGUMENTS"
```

`aise_run_init.py` 串起整个 run lifecycle：
1. 解析 `.aise/plan.json`（详见 `docs/plan-schema.md`）
2. 校验：schema_version / task_title / 每个 task 的 task_id+scope.paths+test_manifest.pipe / dependencies 无环 / shared_evidence scope 相交
3. 失败 → exit 2 + 列出违规项
4. 通过 → 创建 `plan.snapshot.json` + `.sha256` + 新 `run_id`（`YYYYMMDD-HHMMSS-<6hex>`）
5. 写 `.aise/runs/<run_id>/run_context.json` 给下游 gate 使用

下游所有 gate（scope_check / verify / fuse / dashboard）启动时第一件事就是校验 snapshot 未被篡改 + 在 `run_context.json` 中找当前 task 的 scope 与配置，关闭"中途偷换 plan"的窗口。

校验失败时它们会 exit 2 + snapshot_tampered 退出，必须重新跑 aise_run_init.py 才能续跑。

### 步骤 3：任务分割阶段（DAG）（优化④）

调用 **`aise-planning-with-files`** skill，产出 `.aise/plan.json`（机器可读）+ `.aise/plan.md`（人类可读），plan.json 字段定义见 [`docs/plan-schema.md`](../docs/plan-schema.md)：

```json
{
  "schema_version": "1.0",
  "task_title": "...",
  "tasks": [
    {
      "task_id": "T-001",
      "title": "...",
      "scope": {"paths": ["src/**", "tests/**"]},
      "acceptance": "...",
      "test_manifest": {"pipe": "pytest-junitxml", "targets": ["tests"]},
      "dependencies": [],
      "shared_evidence_tasks": []
    }
  ]
}
```

`test_manifest.pipe` 必须是 v3.5 支持的 **6 种** 之一：
`go-test-json-to-junit` / `mvn-surefire` / `pytest-junitxml` / `jest-junit` /
`cargo-test-junit` / **`cargo-nextest-junit`**（v3.5 新增，推荐 Rust 项目优先用）。

**Rust 项目两种选择**：
- `cargo-test-junit`：零外部依赖（cargo2junit 通过 RUSTC_BOOTSTRAP=1 启用），但触
  碰 stable Rust 逃生口，[详见 docs/rustc-bootstrap-risk.md](../docs/rustc-bootstrap-risk.md)
- `cargo-nextest-junit`：原生 stable Rust + 更快 + 不触碰 unstable，但需用户先跑
  `cargo install cargo-nextest --locked`

### 步骤 4：任务执行阶段（小模型 + TDD）（优化③⑥⑨）

对每个并行组的每个任务：

1. **结构化上下文注入**：自动通过 SessionStart hook 调用 `aise_inject_context.py`，将以下内容注入：
   - 全局 `CLAUDE.md`
   - 项目 `MEMORY.md` 与相关 `docs/spec/` 片段
   - 命中关键词的 `.aise/patterns/` 与 `~/.claude/docs/patterns/`
   - 本任务 AC

2. **TDD 强制前置**：调用 **`aise-test-driven-development`** skill 完成 Red → Green → Refactor

3. **使用 SubAgent 隔离上下文**：通过 `Agent` 工具派发到独立子代理（`subagent_type: general-purpose` 或 `Explore`），加 `isolation: worktree` 避免污染

4. **Scope Gate（v3.3 架构）**：worker 完成代码改动后、commit 前强校验：

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_scope_check.py" \
       --project-root "$(pwd)" \
       --task-id "T-001"
   ```

   读最新 `.aise/runs/<run_id>/run_context.json`，校验 `git diff` 中所有变更文件都落在 task.scope.paths 之内：
   - exit 0：通过
   - exit 1：越界（列出违规文件 + scope）→ worker 必须回退非范围内的改动
   - exit 2：状态异常（run_context 缺 / snapshot 篡改 / task_id 未知）

5. **客观验证门禁**：见步骤 5 → `aise_verify.py`，整体复用 plan.snapshot + evidence 链路

### 步骤 5：客观验证门禁（硬门禁）（优化① + v1.1 machine signoff）

调用 **`aise-verification-before-completion`** skill，并强制执行：

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py"
```

脚本会（v1.1 新增能力以 ⬅ 标注）：
- ⬅ 启动门禁：校验 `plan.snapshot.json` 未被篡改（snapshot 不存在则跳过）
- 自动检测项目类型（Maven/Gradle/npm/Python）
- ⬅ **工具预检**：每个 runner 跑前先查 PATH 上有无对应 bin，缺失直接 exit 127 并打印平台特定安装命令（brew/apt/winget）
- 运行测试、Lint、类型检查
- ⬅ **evidence 签收**：每个 runner 产出的 JUnit XML / 命令 stdout 转储被 sha256 + mtime 记录到 `.aise/runs/<run_id>/evidence.jsonl`
- 任一失败 → 退出码 1 → 强制返回步骤 4 重试

退出码语义：
- `0` 通过 + evidence 链已签收
- `1` 业务失败（测试红）
- `2` 状态异常（snapshot 不存在/被篡改）
- `127` 环境异常（必需工具缺失）

**evidence 复核**（步骤 6 调用前可选执行）：

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py" --verify-evidence
```

重新读取最近一次 run 的 `evidence.jsonl`，对每个 artifact 重算 sha256 + 检查 mtime 仍在生成窗口内（容忍 ±2s）。任何篡改 → exit 1 列出违规项。审查阶段不再信任 Agent 自报"测试通过了"，而是用机器签收做信任根。

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

## v1.1 升级（方案 A）

本版本不引入 Node.js / `.cjs` 重写，仅在原 Python 脚本上增加 3 个高 ROI 子项：

1. **machine signoff** — `aise_verify.py` 每个 runner 产出的 evidence（JUnit XML / stdout）经 sha256 + mtime 签收，写 `.aise/runs/<run_id>/evidence.jsonl`，下游可 `--verify-evidence` 复核
2. **plan snapshot 防篡改** — `aise_snapshot.py create` 在用户 ExitPlanMode 后锁定 plan，所有 gate 启动校验 sha256，关闭中途篡改窗口
3. **工具预检 + 安装指引** — 缺 mvn/gradle/npm/pytest 时 fail-fast exit 127 + brew/apt/winget 命令

v3.2.5 文档里的 targetCovers / `--pipe` runner / Node 重写等高复杂度子项**未实施**，待 Spike 后再评估必要性。
