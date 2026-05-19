# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v3.6.0] — 2026-05-19

### 一句话

> 工程质量收敛版：v3.5 cargo-nextest CI 跨平台全过、aise_doctor --export
> 导出报告到文件、**v3.2.5 §17.1 240 测试目标 100% 达成**（241/241 全绿）。

### Added

#### `aise_doctor --export <path>`
- 把 doctor 报告写到指定文件
- 默认 markdown 格式；与 `--json` 组合写 JSON
- stdout 同时输出（CLI 体验不变）
- 父目录自动创建 / 覆盖已存在文件
- 与 `--check-versions` 组合时版本章节也写入文件
- 6 个单元测试

#### GitHub Actions `v3_5-cargo-nextest` job
- matrix: ubuntu-latest + macos-latest
- 用 `taiki-e/install-action@v2` 装预编译 nextest 二进制（替代 `cargo install`，
  快 10x+）
- 跑 `tests/test_cargo_nextest.py` 含端到端 acceptance

#### lib 模块直接单元测试（v3.6 补充覆盖）
- `tests/test_snapshot.py` (11): create / check 4 状态 / **process-local cache
  (v3.2.5 P1-D 核心防长跑篡改)** / require_snapshot helper
- `tests/test_preflight.py` (11): detect_platform / preflight 全路径 / alt_bins
  优先级 / preflight_or_exit / TOOL_DEPS schema 完整性
- `tests/test_doctor_check_versions.py` +5: 边界场景（unknown / skip / python
  特殊路径 / v 前缀 / check_all_versions 完整性）

### Fixed

#### Workflow #11 v3.5 cargo-nextest pipe fail（mac + ubuntu）
根因（2 个）：
1. `--message-format libtest-json` 在 stable Rust 仍是 unstable feature，
   stable 工具链拒绝
2. nextest 不会默认输出 JUnit XML — 必须在项目 `.config/nextest.toml`
   配置 `[profile.<name>.junit]` 段

修复:
- 新增 `tests/fixtures/cargo-sample/.config/nextest.toml` 启用 default
  profile 的 JUnit 输出
- `aise_event.run_cargo_nextest_pipe` 去掉 `--message-format libtest-json`
  参数，让 nextest 跑默认 reporter
- JUnit 拷贝策略改进：扫描 `target/nextest/*/junit.xml` 取最新（兜底多
  profile 场景）

Workflow #12 验证：**18 jobs 全 success**，含 nextest mac + ubuntu。

### Changed
- README.md：6 pipe 表格新增 cargo-nextest-junit ⭐ 推荐标记 + 推荐理由
- docs/aise-guide.md §5.2：手动跑各阶段新增 cargo-nextest + doctor
  `--check-versions` / `--export` 示例

### Tests
- **v3.2.5 §17.1 240 测试目标达成**：241 全绿 + 1 skip / 17.39s（不含 mvn
  端到端 6 个，共 247）
- 覆盖率：
  · 7 个 lib 模块全部有直接单元测试
  · 11 个 scripts/aise_*.py 主流程通过 acceptance 间接覆盖
  · 6 pipe runner 各有 fixture 端到端验收

### CI
- Workflow run 累计 12 次 / 4 个 fail-fix 循环
- 最新 #12：**18 jobs / 全 success**
  · Python unit 6 (3 OS × 2 Python)
  · spike1-go 2 / spike2-maven 1 / spike3-pytest 3 / spike3-jest 2 /
    spike3-cargo 2 / **v3_5-cargo-nextest 2**
- Windows pytest pipe CI 实测全过（v3.3 P0-2/3 ctypes pid + UTF-8 stdio
  方案有效）

### Known Issues / Deferred
- aise_track 与 evidence 链路对齐：继续 deferred（评估后判定低价值）
- aise_gate_context.py：继续 deferred（run_context.json 已含 per-task 信息）
- NTFS hard-link 跨盘**真实**测试（mock 已覆盖；Windows 真机未做）

### Roadmap → v3.7
- 默认推 cargo-nextest，cargo-test-junit 降级为 fallback（用户 opt-in）
- v3.4/5/6 完成度报告整合（团队 review 用）
- pytest pipe 在 jest/cargo 也加 Windows job
- v3 完整流程图（架构图 docx/svg）

### Commit Range (v3.5.0 → v3.6.0)
```
fb3eff3 docs: CHANGELOG v3.5.0 release notes  [v3.5.0 tag]
812c976 ci: v3.6 — 加 cargo-nextest CI job
ecaa0df fix+feat: v3.6 — nextest CI 修 + doctor --export
67ab99f test: v3.6 — 达成 240 测试目标
```

---

## [v3.5.0] — 2026-05-18

### 一句话

> v3.4 + v3.5 双版本工程化深耕：第 **6 个 pipe** `cargo-nextest-junit` 引入
> 消除 `RUSTC_BOOTSTRAP=1` 长期依赖、AGENTS.md onboarding 体系、
> `aise_doctor` 增强（region detect + 镜像建议 + 版本对比）、ANSI 颜色过滤、
> NTFS hard-link 边界全场景覆盖。

### Added

#### 第 6 个 pipe runner: `cargo-nextest-junit`（v3.5）
- `cargo nextest run --message-format libtest-json` 原生 JUnit 输出
- **无需 `RUSTC_BOOTSTRAP=1`**（stable Rust 即可）
- 更快：nextest 并行 + 独立进程隔离
- runtime_bin = cargo（nextest 是 cargo 子命令）
- preflight 校验 cargo-nextest 子命令
- 复用 `_parse_cargo_targets`（XML 格式与 cargo2junit 兼容）
- 文档：`docs/rustc-bootstrap-risk.md` §6 路线图落地

#### AGENTS.md onboarding（v3.5）
让未来 AI 会话只读这一个文件就能 onboard：
- 三阶段闭环图 + 5/6 pipe 总表 + 4 层组件
- 13+ 个已踩过的坑（含工程经验沉淀）
- 跨平台关键差异表
- 常用命令 + 测试体系 + 完整版本时间线
- 接手要点 7 条

#### aise_doctor 增强（v3.4 + v3.5）
- `--region <cn/us/global>`：自动检测（env / timezone）+ 显示镜像建议
- 「🌏 镜像建议」章节：brew / maven / pip / npm / cargo 5 类工具 + setup_command
- `--check-versions`：实际跑 `--version` 拿版本号，与 `tool-compatibility-matrix.md`
  最低版本对比
- `version_check.py`：MINIMUMS 字典 + parse_version 宽松正则 + meets_minimum 元组比较

#### 文档体系（v3.4 + v3.5）
- `docs/tool-compatibility-matrix.md`：5 pipe × {runtime / runner 工具 /
  Spike 实测 / CI 实测} 完整版本支持矩阵
- `docs/rustc-bootstrap-risk.md`：RUSTC_BOOTSTRAP=1 风险评估 + v3.5 cargo-nextest
  路线图
- `AGENTS.md`：项目级 AI onboarding

#### lib 新增模块
- `lib/region_detect.py`：region 探测（env + timezone，不做 DNS）
- `lib/mirror_config.py`：CN region 5 类工具镜像配置
- `lib/ansi.py`：CSI/OSC/单字符 escape 三类 sequence 过滤
- `lib/version_check.py`：MINIMUMS + parse_version + check_all_versions

#### 测试套件扩充
- `test_region_mirror.py` (17): region detect + mirror_config + doctor 集成
- `test_ansi.py` (19): CSI/OSC/SGR/256 色/truecolor/真实 mvn/cargo 样本/bytes
- `test_doctor_check_versions.py` (11): parse_version + meets_minimum + doctor 集成
- `test_cargo_nextest.py` (8): PIPE_DEFS 注册 + preflight + parse + skipif acceptance
- `test_surefire_collector.py` +8: 6 种 OSError errno parametrize + link+copy 双失败

### Changed
- `lib/ansi.maybe_strip` 集成到 `aise_event.py` 5 个 runner 的 stdout/stderr dump
  写盘前过滤（mvn / cargo / npm 等 TTY 颜色码不再污染 dump.log）
- `aise_doctor.py` markdown 输出新增「🔢 版本检查」章节
- `PIPE_DEFS["cargo-nextest-junit"]` 加入，pipe 总数从 5 → **6**

### Fixed
- (无 v3.4/v3.5 期间引入的 bug；纯增量功能)

### Engineering Insights（新增）
1. **PIPE_DEFS.bin ≠ runtime_bin** 的设计教训进一步泛化到 cargo-nextest（preflight
   验子命令存在，runtime 跑 `cargo nextest run`）
2. **Windows pid 探测**：实测 GitHub Actions Windows runner py3.10/3.12 全过
   （v3.3 P0-3 实战验证 ctypes kernel32.OpenProcess + STILL_ACTIVE=259 方案有效）
3. **国内 GitHub SSH 22 端口偶发阻断**：本会话期间 GitHub SSH 22/443/HTTPS 同时
   被 reset 约 1 小时；本地累积 6 commit 待 push，最终用户切网络成功
4. **`cargo nextest --message-format libtest-json`** 是 nextest 0.9.50+ 引入的
   稳定 JUnit 输出方式，比早期 `--message-format junit` 更可靠

### Known Issues / Deferred
- cargo-nextest acceptance 端到端测试在本地 mac 跑通需 `cargo install cargo-nextest`
  （未做，pytest.skipif 兜底）；GitHub Actions 也未加 nextest job（v3.6 待做）
- aise_track 与 evidence 链路对齐：评估后判定 track 是过程信号，evidence 是产物
  签收，本质不同；改造价值低，继续 deferred

### Roadmap → v3.6
- 给 GitHub Actions 加 cargo-nextest job（mac + linux）
- 默认推 cargo-nextest，cargo-test-junit 降级为 fallback（用户 opt-in）
- `aise_doctor --doctor-export` 导出 markdown 报告到文件
- 240 测试目标（当前 208，剩余 32）

### Commit Range (v3.4 → v3.5)
```
v3.4.x (pushed):
  249c355 feat: v3.4 aise_doctor.py
  26d4f7d docs: v3.4 tool-compatibility-matrix

v3.4 P2 (本批):
  4d6756d feat: v3.4 P1-3 region detect + 镜像推荐
  8ddd0c4 feat: v3.4 P2-1 ANSI 颜色码过滤
  696a7f7 docs: v3.4 P2-2 RUSTC_BOOTSTRAP=1 风险评估

v3.5 (本批):
  1a0fbb0 feat: v3.5 AGENTS.md onboarding + NTFS hard-link 边界增强
  1c9bc24 feat: v3.5 P1-2 aise_doctor --check-versions
  6cf73eb feat: v3.5 cargo-nextest-junit 第 6 个 pipe
```

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
