# Spike-3 完成度报告：5 种 pipe runner 全集落地

生成时间：2026-05-17
范围：AISE v2.3.x Spike-3（v3.2.5 §18.3 语言扩展阶段）

> 按 v3.2.5 设计，Spike-1 单 runner 验证最关键设计 → Spike-2 横向扩展跨平台 →
> Spike-3 覆盖 5 种 pipe 全集（go / mvn / pytest / jest / cargo）。

---

## 1. 5 种 pipe 全集状态

| Pipe | 实现 | Fixture | 端到端验收 | parent_package 提取策略 |
|---|:---:|:---:|:---:|---|
| `go-test-json-to-junit` | ✅ Spike-1 | tests/fixtures/go-sample/ | 6 用例 PASS | `<system-out>` JSON events fallback 提 `Package` 字段（v2 默认 suite.name 空） |
| `mvn-surefire` | ✅ Spike-2 | tests/fixtures/maven-sample/ | 6 用例 PASS（7m37s）| classname rsplit('.', 1)[0]，对应 Maven fully-qualified class 前缀 |
| `pytest-junitxml` | ✅ Spike-3 | tests/fixtures/python-sample/ | 5 用例 PASS | classname rsplit('.', 1)[0]，对应 Python 模块前缀 |
| `jest-junit` | ✅ Spike-3 | tests/fixtures/jest-sample/ | 4 用例 PASS | testsuite.name = 顶层 describe 名 |
| `cargo-test-junit` | ✅ Spike-3 | tests/fixtures/cargo-sample/ | 3 用例 PASS | classname = Rust 模块路径（cargo2junit 实测约定） |

**结论**：v3.2.5 §4.4.5.1 设计的 5 种 pipe 全部落地实现 + 真实样本端到端验证。

---

## 2. 测试覆盖矩阵

```
Spike-1 (41):
  test_lock.py                            10  跨平台锁
  test_event_runner.py                    12  preflight + defense
  test_target_cover.py                    13  cross-kind 桥接
  test_spike1_acceptance.py                6  Go pipe 端到端

Spike-2 (37):
  test_surefire_collector.py              10  hard-link + EXDEV 回退
  test_evidence_mtime_boundaries.py       21  ±2s 容忍精确边界
  test_spike2_acceptance.py                6  mvn-surefire 端到端

Spike-3 (12):
  test_spike3_pytest_acceptance.py         5  pytest-junitxml 端到端
  test_spike3_jest_acceptance.py           4  jest-junit 端到端
  test_spike3_cargo_acceptance.py          3  cargo-test-junit 端到端

合计：90 测试  (78 全绿 < 5s; +6 mvn 端到端 7m37s)
```

---

## 3. 各 pipe 实现路径与关键细节

### 3.1 `pytest-junitxml`
- 命令形式：`pytest --junit-xml=<out>/junit.xml <targets>`
- 优先级：`shutil.which("pytest")` → `python3 -m pytest` 验证 alt_bins
- 默认 target：`tests`
- 注意：pip --user 装的 pytest 不在 PATH，必须用 `python -m pytest` 兜底

### 3.2 `jest-junit`
- 命令形式：`./node_modules/.bin/jest`（fixture 内）+ `jest-junit` reporter
- 通过 `JEST_JUNIT_OUTPUT_DIR` / `JEST_JUNIT_OUTPUT_NAME` 环境变量控制输出
- preflight bin = `node`（不是 `jest`，因为 jest 通常在 fixture 内 ./node_modules）
- 注意：jest-junit reporter 在 package.json 内配置 reporters 数组

### 3.3 `cargo-test-junit`
- 命令形式：`cargo test --no-fail-fast -- -Z unstable-options --format json --report-time`
- stable Rust 需 `RUSTC_BOOTSTRAP=1` 启用 `-Z unstable-options`
- cargo stdout 夹杂非 JSON 行（"Compiling" / "Finished" / "Running"），过滤
  以 `{` 开头且 `}` 结尾的行后再喂 cargo2junit
- 注意：PIPE_DEFS 的 bin 是 `cargo2junit`（preflight 工具），cargo 本身由
  runner 通过 `shutil.which("cargo")` 自找

---

## 4. 工程发现（仅文档评审不可见）

### 4.1 preflight_pipe 必须支持 `alt_bins`
- pip --user 装 pytest 让 `shutil.which("pytest")` 失败
- 解决：PIPE_DEFS 加 `alt_bins: ["python3 -m pytest", "python -m pytest"]`
- 实际 `import` 验证模块存在性（preflight.py 复用 `_python_module_available`）

### 4.2 PIPE_DEFS.bin 不一定是真实执行命令
- jest-junit 真正执行 fixture 内 `./node_modules/.bin/jest`，preflight 只验 node
- cargo-test-junit preflight 验 cargo2junit，真正还需要 cargo（runner 自找）
- 设计教训：preflight 只保证"我能用"，runner 负责"我能跑"

### 4.3 cargo test JSON 输出格式陷阱
- stable Rust 不允许 `-Z unstable-options`，需 `RUSTC_BOOTSTRAP=1` 绕开
- cargo test stdout = JSON events + 编译信息混合，必须过滤
- cargo2junit 对纯空 stdin 也会输出空 `<testsuites/>`，看似 OK 但 actual_targets = []

### 4.4 jest 与 jest-junit 的 reporters 配置耦合
- jest-junit 必须在 package.json 的 jest.reporters 数组里配置才生效
- 单独 `--reporters=jest-junit` CLI flag 在 Jest 29 已不推荐
- AISE 文档应建议用户在 package.json 中预配

### 4.5 国内网络环境对镜像依赖严重
- brew install 卡在 USTC 镜像 update 阶段（>20min 无输出）
- Maven 阿里云镜像可用，Maven 央仓不可达
- 国内场景 v3.3 应加 region detect → 自动用国内镜像

---

## 5. v3.3 路线图更新

按 Spike-3 经验，v3.3 落地前必修任务（继承 spike-2-compatibility.md 列表 +
本报告新增）：

### 跨平台（继承 spike-2-compatibility）
1. P0: GitHub Actions Linux + Windows runner 跑全 90 测试
2. P0: defense_in_depth_check 路径分隔符归一（Windows）
3. P0: `_check_pid_alive` Windows 显式 STILL_ACTIVE 判定

### Spike-3 新增
4. P1: PIPE_DEFS 支持 `runtime_bin` 区分 preflight bin 与执行 bin（消除
   jest/cargo 的隐式约定）
5. P1: `preflight_pipe(project_root=...)` 支持检查项目内 `./node_modules/...`
6. P2: 镜像 region detect（brew/maven/pip）
7. P2: cargo `RUSTC_BOOTSTRAP=1` 安全风险评估（绕过 stable 限制可能带来
   未来 Rust 版本兼容性问题）

### 工具版本兼容性矩阵
8. P2: 编写各 pipe 工具最低支持版本表：
   - go-junit-report v1 vs v2（v2 默认 suite.name 空，v1 不同）
   - jest 28/29/30 reporter 接口变更
   - cargo2junit vs cargo-nextest（后者输出 JUnit 更原生）

---

## 6. Spike-3 已知不会修复的边界

- **网络依赖**：jest fixture 需 npm install（联网装 ~30MB 依赖）；cargo
  fixture 需要本地装 rust toolchain + cargo2junit。v3.3 应在 `aise_doctor.cjs`
  自检这些依赖
- **测试隔离**：jest acceptance 用 symlink 共享 node_modules，cargo
  acceptance 用 symlink 共享 target/。这是 Spike 速度优化，生产环境
  应每次干净 install / build
- **xterm 颜色 ANSI 码**：mvn / cargo 在 TTY 中输出带 ANSI 颜色，stdout dump
  原样保留。v3.3 应可选过滤
- **doc-tests**：cargo 默认运行 doc-tests，本 fixture 没有 doc-tests
  所以 spike3-cargo 第二个 testsuite 为空。生产场景需要处理

---

## 7. 一句话结论

> Spike-3 在 macOS 平台完整跑通 5 种 pipe 全集。设计实现验证完毕，下一步
> 走 v3.3 全量落地（30-40d）+ GitHub Actions 跨平台矩阵补齐 Linux/Windows
> 覆盖。**Spike 路径胜利**——慢就是快，3 个 Spike 共 13.5d（评估方估算）暴露了
> 12+ 个文档评审看不出的工程问题，每个都有具体 fixture + 测试佐证。

---

_本报告由 焦小糖团队（Anthropic Claude Code, Opus 4.7）生成。Spike-3 完成度
报告 v1.0。_
