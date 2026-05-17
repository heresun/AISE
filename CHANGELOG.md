# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v3.3.0] — 2026-05-17

### 一句话

> v3.2.5 §18 全量落地：5 种语言 pipe runner 全集 + 三阶段闭环 gate + 跨平台
> CI（含 Windows）+ machine signoff 端到端可用。

### Added

#### 5 种语言 pipe runner（Spike-1/2/3）
- `go-test-json-to-junit`：Go 项目 `go test -v -json | go-junit-report`
- `mvn-surefire`：Maven Surefire/Failsafe XML hard-link 收集 + copy 回退
- `pytest-junitxml`：Python `pytest --junit-xml`
- `jest-junit`：JS/TS fixture 内 `./node_modules/.bin/jest`
- `cargo-test-junit`：Rust `cargo test -- --format json | cargo2junit`

#### 三阶段闭环 gate（v3.3 架构补完）
- `aise_run_init.py`：ExitPlanMode 入口，plan 校验 + run_id 分配 + snapshot 锁
- `aise_scope_check.py`：git diff vs `task.scope.paths` 强 gate
- `aise_event.py`：5 pipe runner 调度 + evidence 签收

#### 跨平台 CI 矩阵
- GitHub Actions `.github/workflows/test.yml`
- 3 平台（macOS / Linux / Windows）× 2 Python（3.10 / 3.12）= 16 jobs
- 包含 Python unit + 5 pipe runner 各自端到端验收

#### machine signoff
- `lib/evidence.py`：sha256 + mtime + 生成窗口的 evidence.jsonl 签收链
- `aise_verify.py --verify-evidence` 复核模式
- `plan.snapshot.json` 防篡改 + process-local in-memory 缓存

#### cross-kind targetCovers 桥接
- `lib/target_cover.py`：declared `kind=package` + actual `kind=testcase` + `parent_package` 命中 → cover
- Spike-1/2/3 各 fixture 端到端验证

#### Windows 一等公民
- `_check_pid_alive_windows`：ctypes 调 `kernel32.OpenProcess` + `GetExitCodeProcess` + `STILL_ACTIVE` (259) 显式判定
- `defense_in_depth_check` 路径分隔符归一（`.\pkg\foo` 自动匹配 `./pkg/**`）
- 全链路 UTF-8 stdio（`PYTHONUTF8=1` + 显式 `encoding="utf-8"`）

#### plan.json schema v1.0
- 完整 schema 定义：`docs/plan-schema.md`
- 校验：schema_version / task_title / scope.paths / test_manifest.pipe /
  dependencies 拓扑无环 / shared_evidence_tasks scope 相交
- 模板：`templates/aise/plan.json`

#### 测试套件
- 本地 135 测试全绿（11.7s，不含 6 mvn 端到端）
- 含 mvn 共 141 测试
- 跨平台 GitHub Actions × 16 jobs 全过

#### 文档体系
- `docs/aise-guide.md`：v3.3 实施指南（v1.0 → v3.3 大改写）
- `docs/plan-schema.md`：plan.json schema 定义
- `docs/spike-2-compatibility.md`：跨平台兼容性报告
- `docs/spike-3-summary.md`：5 pipe 全集落地报告
- `docs/v3.3-completion-report.md`：v3.3 完成度报告（团队 review 用）
- README.md：顶层入口重写（含 CI badge / 测试 badge / 平台 badge）

### Changed
- `PIPE_DEFS` 引入 `runtime_bin` 字段（v3.3 P1-1），分离 preflight bin 与
  实际执行 bin，避免 jest/cargo 的隐式约定（runner 自己手动 shutil.which）
- `commands/aise.md` 主流程更新：v1.1 旧 snapshot 入口 → v3.3 推荐 aise_run_init
  一步到位 + 步骤 4 新增 Scope Gate 子步骤

### Fixed
- Workflow #3 Windows Python unit (3.10/3.12) 失败：cp1252 解码中文 stderr →
  `PYTHONUTF8=1` 环境变量 + subprocess 显式 `encoding="utf-8"` 双层防御
- go-junit-report v2 默认 `<testsuite name="">` 空：`<system-out>` JSON
  events fallback 解析 Package
- cargo test stdout 混编译信息：过滤 `{...}` 开头/结尾的纯 JSON 行后再喂
  cargo2junit
- shared_evidence scope 简单 head segment 误判（"src/auth" vs "src/billing"
  被误判相交）：改用静态前缀 + 严格 prefix 包含判定

### Engineering Insights（仅文档评审看不见的工程问题）
1. preflight 与 runtime bin 分离的设计教训：preflight 只保证"我能用"，
   runner 负责"我能跑"
2. 国内网络环境对镜像依赖严重（brew 卡 USTC 20min+，需阿里云直接下载）
3. 企业内网 nexus 必须 override（fixture `.mvn/maven.config` + `settings.xml`）
4. Java 26 + Maven 3.9.9 触发 jansi/guava restricted method warning（不影响功能）
5. `-set-exit-code` flag 让 junit_proc 继承测试失败 → pipeline_ok 判定改用
   "XML 落盘 + 可解析"
6. cargo `RUSTC_BOOTSTRAP=1` 绕开 stable Rust 限制（未来版本兼容性风险）
7. git status --porcelain 折叠 untracked 目录：用 `git diff --name-only` +
   `git ls-files --others` 组合

### Known Issues / Deferred
- `aise_track` 与 evidence 链路对齐：评估为低价值，降级到 v3.4 后视用户反馈
- `aise_gate_context.py generate`：run_context.json 已含全部 per-task 信息，
  独立 gate_context 文件冗余，待 per-task 调优参数增多再做
- WSL2 跨边界（WSL 跑 Maven，target/ 落 NTFS 挂载）的跨盘 hard-link 实测
  未做（collector copy 回退已覆盖代码路径）
- 工具版本兼容性矩阵文档（go-junit-report v1/v2 / Jest 28-30 等）

### Roadmap → v3.4
- `aise_doctor.py`：5 pipe 工具链 + 版本兼容性自检（最高 UX 价值）
- 镜像 region detect（brew/maven/pip 国内镜像自动）
- 工具版本兼容性矩阵
- ANSI 颜色过滤选项
- NTFS 跨盘 hard-link 真实测试
- v3.2.5 P2-C 文档更正
- 240 测试目标（当前 135）

### Commit Range
```
e195c08..22f0d2c   (11 commits)

22f0d2c docs(aise): v3.3 完成度报告 + 用户指南升级 + README 重写
f08059c fix(aise): Windows Python unit CI 失败 — 全链路 UTF-8 stdio
6c3b9d9 feat(aise): v3.3 架构补完 — run_init + scope_check 三阶段闭环
61cfb95 refactor(aise): v3.3 P1-1 — PIPE_DEFS 分离 preflight_bin / runtime_bin
74209ee feat(aise): v3.3 P0 — 跨平台 CI + Windows 路径分隔符 + Windows pid 探测
f6bc813 feat(aise): Spike-3 pytest + jest + cargo 3 种语言 runner，5 pipe 全集闭环
fe0e729 feat(aise): Spike-2 mvn-surefire + mtime 边界 + 跨平台兼容性报告
b652361 feat(aise): Spike-1 跨平台锁 + Go pipe + targetCovers 救命路径
59458e9 feat(aise): v1.1 plan snapshot + machine signoff 实施
e39d3a2 docs(aise): 更新 v1.1 命令规范 — plan snapshot + machine signoff
e195c08 feat: AISE 过程增强审查机制 v1.0.0  (baseline)
```

---

## [v1.0.0] — earlier baseline

详见 e195c08 commit。AISE v1 9 阶段任务流程编排基础设施。
