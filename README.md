# AISE — Claude Code 插件（v3.3）

> **AISE 过程增强审查机制**：端到端任务流程编排 + 机器签收（machine signoff）+
> 5 种语言 pipe runner + 三阶段闭环 gate。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/heresun/AISE/actions/workflows/test.yml/badge.svg)](https://github.com/heresun/AISE/actions/workflows/test.yml)
[![Tests](https://img.shields.io/badge/tests-135%20passing-brightgreen)](#-测试覆盖)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-blue)](#-跨平台)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue)](#-跨平台)

---

## ✨ v3.3 核心特性

### 🔒 machine signoff（机器签收，v1.1+）
每个 runner 产出的 JUnit XML / stdout dump 被 **sha256 + mtime + 生成窗口**
记录到 `.aise/runs/<run_id>/evidence.jsonl`。下游 gate 不再信任 Agent 自报
"测试通过了"，而是重读 evidence 校验：
- sha256 不匹配 → `evidence_tampered`
- mtime 出窗口 ±2s 容忍 → `evidence_window_violation`

### 🎯 三阶段闭环 gate（v3.3 新增）
```
ExitPlanMode → aise_run_init.py (plan 校验 + run_id)
   → worker TDD → aise_scope_check.py (git diff vs scope)
   → aise_event.py (5 pipe) → aise_verify.py --verify-evidence
```

### 🌐 5 种语言 pipe runner（Spike-1/2/3）

| Pipe | 适用 | 工具 | 端到端验收 | CI 平台 |
|---|---|---|:---:|---|
| `go-test-json-to-junit` | Go | `go-junit-report` | 6 ✅ | macOS + Linux |
| `mvn-surefire` | Java/Kotlin | `mvn` | 6 ✅ | Linux |
| `pytest-junitxml` | Python | `pytest` | 5 ✅ | **macOS + Linux + Windows** |
| `jest-junit` | JS/TS | fixture 内 jest | 4 ✅ | macOS + Linux |
| `cargo-test-junit` | Rust | `cargo` + `cargo2junit` | 3 ✅ | macOS + Linux |

### 🛡️ plan.snapshot.json 防篡改（v1.1+ + v3.2.5 P1-D）
gate 进程启动时一次性把 snapshot 读入内存，process-local 缓存。盘上
被中途篡改不影响本 gate 进程，关闭"中途偷换 plan"窗口。

### 🔍 cross-kind targetCovers 桥接（v3.2.5 §12.3）
declared `kind=package` + actual `kind=testcase` 且 `parent_package` 命中
→ 视为 cover。让 plan 用粗粒度 package 表达，runner 自动从 testcase 桥接。

### 🪟 Windows 一等公民
- `defense_in_depth_check` 路径分隔符归一（`.\pkg\foo` 自动匹配 `./pkg/**`）
- `_check_pid_alive` Windows 显式 ctypes 调 `kernel32.OpenProcess` +
  `GetExitCodeProcess` + 比对 `STILL_ACTIVE`（259），避免 stale 锁卡死
- 全链路 UTF-8 stdio（`PYTHONUTF8=1` + 显式 `encoding="utf-8"`）

---

## 🚀 快速开始

### 安装

```
/plugin marketplace add https://github.com/heresun/AISE
/plugin install aise@aise
```

或本地开发：
```bash
git clone https://github.com/heresun/AISE ~/.claude/plugins/marketplaces/aise
```

### 使用

```
/aise 给 data-bank 增加批量导出功能
```

整个流程 9 阶段串行/并行执行，全程跨平台。详见
[docs/aise-guide.md](docs/aise-guide.md)。

### 手动跑各阶段

```bash
# v3.3 推荐入口（一步到位：plan 校验 + run_id + snapshot + run_context）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_run_init.py" \
    --project-root "$(pwd)" \
    --task-title-override "我的任务"

# 单 task scope gate（worker commit 前调）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_scope_check.py" \
    --project-root "$(pwd)" \
    --task-id "T-001"

# 跑 pytest pipe（其他 4 种 pipe 类似）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_event.py" \
    --pipe pytest-junitxml \
    --project-root "$(pwd)" \
    --run-id <run_id>

# evidence 复核（机器签收）
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_verify.py" --verify-evidence
```

---

## 📦 项目结构

```
aise/
├── .claude-plugin/         marketplace.json + plugin.json
├── .github/workflows/      GitHub Actions CI 矩阵
├── commands/aise.md        /aise slash command
├── skills/                 6 个内置 Skill（aise- 前缀）
├── scripts/
│   ├── aise_run_init.py    ★ v3.3 入口（plan 校验 + run_id）
│   ├── aise_event.py       ★ 5 pipe runner 调度
│   ├── aise_scope_check.py ★ v3.3 scope gate
│   ├── aise_verify.py      v1.1+ machine signoff
│   ├── aise_snapshot.py    plan.snapshot create/check/show
│   ├── aise_init/track/fuse/inject_context/sediment/dashboard.py
│   └── lib/
│       ├── lock.py             跨平台 mkdir 锁 + Windows ctypes pid
│       ├── event_runner.py     PIPE_DEFS + preflight + defense + runtime_bin
│       ├── target_cover.py     cross-kind targetCovers
│       ├── evidence.py         sha256 + mtime 签收链
│       ├── snapshot.py         plan.snapshot.json 防篡改
│       ├── preflight.py        通用工具预检 + 平台指引
│       └── surefire_collector.py  Maven XML hard-link + copy 回退
├── tests/
│   ├── test_lock / event_runner / target_cover / evidence_mtime ...
│   ├── test_aise_run_init / aise_scope_check / runtime_bin ...
│   ├── test_spike[1,2,3]_*_acceptance.py
│   └── fixtures/
│       ├── go-sample/      Go fixture（Spike-1）
│       ├── maven-sample/   Maven fixture（Spike-2，含阿里云镜像 .mvn config）
│       ├── python-sample/  Python fixture（Spike-3）
│       ├── jest-sample/    Jest fixture（Spike-3）
│       └── cargo-sample/   Rust fixture（Spike-3）
├── templates/aise/         .aise/ 工作区模板（含 plan.json）
├── hooks/hooks.json        PostToolUse + SessionStart 自动注册
├── docs/
│   ├── aise-guide.md                v3.3 实施指南
│   ├── plan-schema.md               plan.json schema v1.0
│   ├── spike-2-compatibility.md     跨平台兼容性
│   ├── spike-3-summary.md           5 pipe 全集落地报告
│   ├── tool-compatibility-matrix.md 5 pipe 工具版本兼容性矩阵
│   └── v3.3-completion-report.md    v3.3 完成度报告
├── LICENSE
└── README.md
```

---

## 🧪 测试覆盖

| 测试套件 | 用例 | 主要内容 |
|---|---:|---|
| `test_lock.py` | 10 | mkdir 原子性 / stale / 并发抢锁 |
| `test_lock_windows_pid.py` | 7 | Windows ctypes STILL_ACTIVE |
| `test_event_runner.py` | 12 | preflight + defense + PIPE_DEFS |
| `test_runtime_bin_resolver.py` | 9 | runtime_bin 4 种解析 |
| `test_target_cover.py` | 13 | cross-kind 桥接 |
| `test_surefire_collector.py` | 10 | hard-link + EXDEV 回退 |
| `test_evidence_mtime_boundaries.py` | 21 | ±2s 容忍精确边界 |
| `test_defense_path_separator.py` | 7 | Windows 路径分隔符归一 |
| `test_aise_run_init.py` | 18 | plan 校验全场景 |
| `test_aise_scope_check.py` | 10 | git diff vs scope |
| `test_spike1_acceptance.py` | 6 | Go pipe 端到端 |
| `test_spike2_acceptance.py` | 6 | mvn-surefire 端到端（7m37s）|
| `test_spike3_pytest_acceptance.py` | 5 | pytest pipe 端到端 |
| `test_spike3_jest_acceptance.py` | 4 | jest pipe 端到端 |
| `test_spike3_cargo_acceptance.py` | 3 | cargo pipe 端到端 |
| **合计** | **141** | 不含 mvn 跑 **135 / 11.7s** |

### GitHub Actions
- 3 平台 × 2 Python = **6 Python unit jobs**
- 加 5 个 pipe runner 各自 job = **16 jobs 总数**
- 累计 4 次 push 跑分：3 次 ✅ + 1 次 ⚠️→✅（Windows UTF-8 fix）

---

## 🌐 跨平台

| 平台 | mkdir 锁 | mtime ±2s | hard-link | pid 探测 | CI |
|---|:---:|:---:|:---:|:---:|:---:|
| macOS APFS | ✅ | ✅ | ✅ | os.kill(pid,0) | ✅ |
| Linux ext4 | ✅ | ✅ | ✅ | os.kill(pid,0) | ✅ |
| Windows NTFS | ✅ | ✅ | ✅ 同盘 | **ctypes kernel32** | ✅ |
| WSL2 ext4 | ✅ | ✅ | ⚠️ 跨盘走 copy | os.kill(pid,0) | ⏸️ |

详见 [docs/spike-2-compatibility.md](docs/spike-2-compatibility.md)。

---

## 🛠️ 工作流总览

```
[文档产出] → [用户对齐 ExitPlanMode] → [aise_run_init: plan 校验 + run_id]
    ↓
[DAG 任务分割 → .aise/plan.json]
    ↓
[并行 SubAgent 组（worktree 隔离）]
    ↓
[TDD: Red → Green → Refactor]
    ↓
[aise_scope_check: git diff vs task.scope.paths]   ← scope gate
    ↓
[aise_event --pipe <P>: 5 pipe runner 之一]        ← 真实测试 + evidence 签收
    ↓
[aise_verify --verify-evidence: sha256 + mtime]    ← machine signoff 硬门禁
    ↓
[多 persona 并行审查（ce-review）]                  ← 软门禁
    ↓
[模式识别熔断（aise_fuse）] → 通过?
    ├─ 是 → 标记完成 → 沉淀 patterns（ce-compound + aise_sediment）
    └─ 否 → 根因分析 → 重试 or 求助用户
```

---

## 📋 plan.json 例子

```json
{
  "schema_version": "1.0",
  "task_title": "实现 Calc 服务",
  "tasks": [
    {
      "task_id": "T-001",
      "title": "Calc.add 实现 + 单测",
      "scope": {"paths": ["src/calc/**", "tests/test_calc*.py"]},
      "acceptance": "calc.add(2,3) == 5",
      "test_manifest": {"pipe": "pytest-junitxml", "targets": ["tests"]},
      "dependencies": [],
      "shared_evidence_tasks": []
    }
  ]
}
```

完整 schema 见 [docs/plan-schema.md](docs/plan-schema.md)。

---

## 📊 v3.3 完成度

详见 [docs/v3.3-completion-report.md](docs/v3.3-completion-report.md)。要点：

- v3.2.5 §18.1 18 项任务：**完成 10 + 部分 1 = 61%**
- 12 项 v3.2.5 finding：**完成 9 项 + 部分 1 项 = 83%**
- 5 pipe 全集：**100%**
- 三阶段闭环：**100%**
- GitHub Actions CI 跨平台：**100%**

剩余 v3.4 路线图：aise_doctor / 镜像 region detect / 工具版本兼容性矩阵
/ 240 测试目标（当前 135） / ANSI 颜色过滤。

---

## 🔁 与现有插件共存

本插件的 6 个 Skill 都是原插件的**重命名副本**（加 `aise-` 前缀），不会冲突：
- 安装 superpowers + aise → 同时拥有 `test-driven-development` 和 `aise-test-driven-development`
- 卸载 superpowers / planning-with-files / compound-engineering 后，AISE 仍可独立工作

---

## 📜 许可证

MIT — 详见 [LICENSE](LICENSE)。第三方 Skill 来源声明见 LICENSE 末尾。

---

## 🙋 反馈与贡献

欢迎 Issue / PR / 经验分享。设计方案演进见 v3.2.5（外部文档）+ 本仓库
docs/spike-*.md 系列。
