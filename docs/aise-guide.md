# AISE 实施指南（v3.3）

> AISE = AI Software Engineering 过程增强审查机制
> 版本：v3.3（v3.2.5 全量落地实施版）
> 适用：Claude Code + Superpowers + Compound Engineering 插件环境

---

## 1. v3.3 整体架构

AISE v3.3 由 **4 层组件** + **3 阶段执行模型** 构成：

### 1.1 组件层次

| 层 | 组件 | 职责 |
|----|------|------|
| 编排层 | `/aise` slash command + skills | 调度阶段，委托现成 Skill |
| 入口层 | `aise_run_init.py` | plan 校验 + run_id 分配 + snapshot 锁 |
| Gate 层 | `aise_scope_check.py` / `aise_verify.py` | scope 边界 + machine signoff |
| 执行层 | `aise_event.py` + 5 pipe runner | 真实测试执行 + evidence 签收 |
| 状态层 | `.aise/` 目录 + `runs/<run_id>/` | 进度、计划、evidence、log |

### 1.2 三阶段闭环

```
ExitPlanMode
    │
    ▼
┌──────────────────────────────────────┐
│ 1. aise_run_init.py                  │
│    · 校验 .aise/plan.json schema     │
│    · 分配 run_id（YYYYMMDD-HHMMSS-X）│
│    · 创建 plan.snapshot.json         │
│    · 写 runs/<run_id>/run_context.json│
└──────────────────────────────────────┘
    │
    ▼ (worker 编码 + TDD)
    │
┌──────────────────────────────────────┐
│ 2. aise_scope_check.py               │
│    · 读 run_context（in-memory 缓存）│
│    · git diff + ls-files            │
│    · 每个文件 vs task.scope.paths    │
│    · 越界 → exit 1                   │
└──────────────────────────────────────┘
    │
    ▼ (Scope ok 后)
    │
┌──────────────────────────────────────┐
│ 3. aise_event.py --pipe <P>          │
│    · preflight 工具 + 防御深度       │
│    · spawn runner (5 选 1)           │
│    · evidence.jsonl 签收            │
│ ─────────────────────────────────── │
│ 4. aise_verify.py --verify-evidence  │
│    · 重读 evidence.jsonl             │
│    · sha256 + mtime ±2s 校验         │
│    · machine signoff                 │
└──────────────────────────────────────┘
```

---

## 2. 5 种测试 pipe runner

每个 task 在 `.aise/plan.json` 的 `test_manifest.pipe` 选一个：

| Pipe | 命令链 | 适用语言 | 工具依赖 |
|---|---|---|---|
| `go-test-json-to-junit` | `go test -v -json \| go-junit-report` | Go | `go` + `go-junit-report` |
| `mvn-surefire` | `mvn test` → 收 `target/surefire-reports/*.xml` | Java/Kotlin | `mvn` |
| `pytest-junitxml` | `pytest --junit-xml=out.xml` | Python | `pytest`（或 `python -m pytest`） |
| `jest-junit` | `npx jest` + reporter `jest-junit` | JS/TS | `node` + fixture 内 `npm install jest jest-junit` |
| `cargo-test-junit` | `cargo test --format json` → `cargo2junit` | Rust | `cargo` + `cargo2junit` |

每个 runner：
- 跑前 `preflight_pipe` 检查工具存在 → 缺失 exit 127 + 平台特定安装指引
- 跑前 `defense_in_depth_check` 校验 target 在白名单 → 越界 exit 2
- 跑后 `collect_artifact` + `write_evidence` 把 JUnit XML / stdout dump 记 sha256 + mtime
- 解析 actual_test_targets[] 含 `source_artifact_path` provenance

---

## 3. plan.json schema（v1.0）

完整定义见 [`plan-schema.md`](plan-schema.md)。最小可工作例子：

```json
{
  "schema_version": "1.0",
  "task_title": "实现 Calc 服务",
  "tasks": [
    {
      "task_id": "T-001",
      "title": "Calc.add 实现 + 单测",
      "scope": {
        "paths": ["src/calc/**", "tests/test_calc*.py"]
      },
      "acceptance": "calc.add(2,3) == 5",
      "test_manifest": {
        "pipe": "pytest-junitxml",
        "targets": ["tests/test_calc.py"]
      },
      "dependencies": [],
      "shared_evidence_tasks": []
    }
  ]
}
```

校验项（aise_run_init.py）：
- 顶级 `schema_version` 必须 `"1.0"`，`task_title` 非空，`tasks` 非空
- 每个 task `task_id` 唯一，`scope.paths` 非空，`test_manifest.pipe` 在 5 种之一
- `dependencies` 无环（DFS 拓扑）、引用必须存在
- `shared_evidence_tasks` scope 与本 task scope 必须相交（除非 `allow_disjoint_shared_evidence: true`）

---

## 4. 文件清单

### 命令与文档
| 路径 | 用途 |
|------|------|
| `commands/aise.md` | `/aise` slash command 主流程定义 |
| `docs/aise-guide.md` | 本文档 |
| `docs/plan-schema.md` | plan.json schema 定义 |
| `docs/spike-2-compatibility.md` | 跨平台兼容性报告 |
| `docs/spike-3-summary.md` | 5 pipe 全集落地报告 |
| `docs/v3.3-completion-report.md` | v3.3 完成度报告 |
| `templates/aise/` | `.aise/` 工作区模板（含 plan.json） |

### 脚本（scripts/）
| 脚本 | 触发 | 用途 |
|------|------|------|
| `aise_init.py` | `/aise` 步骤 0 | 初始化 .aise/ 目录 + 拷贝模板 |
| `aise_snapshot.py` | v1.1 旧入口 | 单独 snapshot create/check/show |
| `aise_run_init.py` | **v3.3 推荐入口** | plan 校验 + run_id 分配 + snapshot + run_context |
| `aise_event.py` | 每个 task TDD 后 | 5 pipe runner 调度，evidence 签收 |
| `aise_scope_check.py` | worker commit 前 | git diff vs task.scope.paths gate |
| `aise_verify.py` | `/aise` 步骤 5 | 客观验证 + evidence 复核 |
| `aise_track.py` | PostToolUse hook | 记录错误模式 |
| `aise_fuse.py` | `/aise` 步骤 7 | 智能熔断判断 |
| `aise_inject_context.py` | SessionStart hook | 注入历史 patterns |
| `aise_sediment.py` | `/aise` 步骤 8 | 沉淀 patterns |
| `aise_dashboard.py` | `/aise` 步骤 9 | 健康度报表 |

### lib/（共用 helper）
| 模块 | 用途 |
|------|------|
| `lib/lock.py` | 跨平台 mkdir 锁 + stale 检测（Windows 用 ctypes 调 kernel32 显式 STILL_ACTIVE）|
| `lib/event_runner.py` | PIPE_DEFS + preflight_pipe + defense_in_depth_check + resolve_runtime_bin |
| `lib/target_cover.py` | targetCovers cross-kind 桥接（testcase→package）|
| `lib/evidence.py` | Evidence artifact 签收链（sha256 + mtime ±2s）|
| `lib/snapshot.py` | plan.snapshot.json 防篡改 + process-local 缓存 |
| `lib/preflight.py` | 通用工具存在性预检 + 平台安装指引 |
| `lib/surefire_collector.py` | Maven Surefire / Failsafe XML hard-link + copy 回退 |

---

## 5. 使用方法

### 5.1 新建 AISE 任务

```
/aise 给 data-bank 增加批量导出功能
```

完整 9 阶段：
1. 文档产出 → 调用 `aise-brainstorming` + `ms-requirements`
2. 用户对齐 → `EnterPlanMode`，ExitPlanMode 后跑 **aise_run_init.py**
3. 任务分割 → 产出 `.aise/plan.json` + `plan.md`
4. TDD 执行 → 调用 `aise-test-driven-development`；commit 前跑 **aise_scope_check.py**
5. 客观验证 → 跑 **aise_event.py + aise_verify.py**（含 evidence 复核）
6. 多 persona 审查 → 调用 `aise-ce-review`
7. 熔断判断 → 跑 `aise_fuse.py`
8. 知识沉淀 → 调用 `aise-ce-compound` + `aise_sediment.py`
9. 健康度报表 → 跑 `aise_dashboard.py`

### 5.2 手动跑各阶段

```bash
# v3.3 推荐入口（一步到位）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_run_init.py" \
    --project-root "$(pwd)" \
    --task-title-override "$ARGUMENTS"

# 单 task scope gate
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_scope_check.py" \
    --project-root "$(pwd)" \
    --task-id "T-001"

# 跑 pytest pipe（其他 pipe 类似）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_event.py" \
    --pipe pytest-junitxml \
    --project-root "$(pwd)" \
    --run-id <run_id>

# 复核 evidence
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py" --verify-evidence
```

### 5.3 中途中断后续跑

`/aise` 自动读取 `.aise/progress.md`，询问是否继续。`run_context.json` 内
保存最新 run_id + plan_snapshot.sha256，gate 启动时自动校验。

---

## 6. 跨平台兼容性

详见 [`spike-2-compatibility.md`](spike-2-compatibility.md)。

| 平台 | mkdir 锁 | mtime ±2s | hard-link | pid 探测 | CI 验证 |
|---|:---:|:---:|:---:|:---:|:---:|
| macOS APFS | ✅ | ✅ | ✅ | os.kill(pid,0) | ✅ |
| Linux ext4 | ✅ | ✅ | ✅ | os.kill(pid,0) | ✅ ubuntu CI |
| Windows NTFS | ✅ | ✅（cp1252→PYTHONUTF8=1）| ✅ 同盘 | **ctypes 调 kernel32 STILL_ACTIVE** | ✅ windows CI |
| WSL2 ext4 | ✅ | ✅ | ⚠️ 跨盘走 copy 回退 | os.kill(pid,0) | ⏸️ |

### Python 编码
- 要求 `PYTHONUTF8=1` 或显式 `encoding="utf-8"`（v3.3 已全链路落地）
- Windows 默认 cp1252 会让中文 stderr 解码失败，必装

### 工具版本

完整 5 pipe 兼容性矩阵 + 升级注意事项见 [`tool-compatibility-matrix.md`](tool-compatibility-matrix.md)。
速查：

- Python 3.10+（CI 跑 3.10 + 3.12）
- pytest 6+
- Maven 3.6+ + maven-surefire-plugin 3.2+
- Node 18+ + jest 29+ + jest-junit 16+
- Rust stable 1.70+ + cargo2junit

---

## 7. machine signoff（v1.1 → v3.3）

AISE 关键设计：**"通过判定"从信任 Agent 自报 → 机器签收**。

### evidence 链路
1. 每个 runner 跑完产出 JUnit XML / stdout dump
2. `evidence.py.collect_artifact` 记录：
   - 文件路径 + sha256 + mtime（ms）
   - 生成窗口 `[window_start_ms, window_end_ms]`
   - source（junit_xml / stdout_dump）
   - runner 名称
3. 落盘 `.aise/runs/<run_id>/evidence.jsonl`
4. 下游 gate (`--verify-evidence`) 重读校验：
   - sha256 不匹配 → `evidence_tampered`
   - mtime 出窗口 ±2s 容忍 → `evidence_window_violation`

### 防篡改窗口
- `plan.snapshot.json` 启动时一次性读入内存（process-local 缓存）
- 即使盘上 plan.snapshot.json 被外部篡改，本 gate 进程不受影响
- 任何 gate 启动时若发现 snapshot 不一致 → exit 2 `snapshot_tampered`

---

## 8. 调参指南

### 熔断阈值（`aise_fuse.py`）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--repeat-threshold` | 2 | 同类错误重复阈值 |
| `--token-budget` | 200000 | 累计 token 上限 |
| `--blast-radius` | 15 | 文件改动数上限 |

### mtime 容忍（`evidence.py`）

`MTIME_TOLERANCE_MS = 2000` ±2s。NTFS 100ns 精度 / APFS 纳秒 / ext4 纳秒
都在此范围内。NFS 跨 server clock skew 可能超 2s，不建议在 NFS 上跑测试。

### scope 策略（plan.json）

```json
{
  "scope_policy": {
    "mtime_window_tolerance_ms": 5000   // 项目级覆盖默认 2000
  }
}
```

---

## 9. 故障排查

### 9.1 `aise_run_init` 校验失败

按 stderr 列出的违规项修 plan.json。常见：
- `schema_version` 不是 "1.0"
- `task_id` 重复
- `test_manifest.pipe` 拼错
- `shared_evidence_tasks` scope 与本 scope 完全不相交

### 9.2 工具缺失 exit 127

按 stderr 平台特定安装命令装。例：
- Go: `go install github.com/jstemmer/go-junit-report/v2@latest`
- Maven: `brew install maven` / `apt install maven` / `winget install Apache.Maven`
- Cargo2junit: `cargo install cargo2junit`

### 9.3 Windows 中文 stderr 乱码

设环境变量：
```
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
```
或在 PowerShell：
```
$env:PYTHONUTF8 = "1"
```

### 9.4 evidence 复核 `evidence_tampered`

通常是：
1. 测试跑完后 worker 手动改了 JUnit XML
2. IDE 或编辑器误修改 evidence 文件
3. 真的有人恶意篡改

排查：`git diff` + 重新跑 runner 重新生成。

---

## 10. v3.3 测试与 CI

### 本地测试
```
cd ~/.claude/plugins/marketplaces/aise
python -m pytest tests/ -v
```

### 跑 mvn 端到端（慢）
```
python -m pytest tests/test_spike2_acceptance.py -v
```

### GitHub Actions CI
- 触发：push 到 main / PR / 手动 `workflow_dispatch`
- 矩阵：3 平台（mac/ubuntu/windows）× 2 Python（3.10/3.12）= **6 python-unit job**
- 加各 pipe runner 单独 job = 16 job 总数
- 详见 [`v3.3-completion-report.md`](v3.3-completion-report.md) §5

---

## 11. 设计原则

- **KISS**：每个脚本职责单一，加起来 ~2200 行
- **零外部依赖**：仅 Python 标准库（dev 用 pytest）
- **可观测**：所有动作产生 JSONL 日志
- **可回滚**：所有破坏性操作有备份
- **证据优先**：硬门禁阻断在主观审查之前
- **machine signoff**：通过判定基于机器签收，不信 Agent 自报

---

## 12. 相关文档

- [`plan-schema.md`](plan-schema.md) — plan.json 完整 schema
- [`spike-2-compatibility.md`](spike-2-compatibility.md) — 跨平台兼容性
- [`spike-3-summary.md`](spike-3-summary.md) — 5 pipe 全集落地报告
- [`v3.3-completion-report.md`](v3.3-completion-report.md) — v3.3 完成度报告
- [`tool-compatibility-matrix.md`](tool-compatibility-matrix.md) — 工具版本兼容性矩阵
- v3.2.5 设计方案（外部）：`AISE-v2.3.2-Gate-Kernel-一步到位优化方案-v3.2.5.md`
