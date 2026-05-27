# AISE 工具版本兼容性矩阵

> v3.4 P1 — 5 种 pipe runner 全集的工具链版本支持范围、已验证组合、
> 已知 gotcha、升级注意事项。
>
> 数据来源：Spike-1/2/3 真实跑通验证 + GitHub Actions CI 4 个 workflow run
> 实测 + 各工具上游文档。版本号"实测"列是确认过的版本，"最低"列是
> 基于行为推测的最低支持版本（保守估计）。

---

## 1. 总览

| Pipe | runtime | runner 工具 | Spike 实测 | CI 实测 |
|---|---|---|:---:|:---:|
| `go-test-json-to-junit` | Go 1.21+ | `go-junit-report v2.1.0+` | Go 1.26.3 / v2.1.0 | Go 1.22 |
| `mvn-surefire` | JDK 11+ + Maven 3.6+ | `maven-surefire-plugin 3.2.5+` | JDK 26 / Maven 3.9.9 / Surefire 3.2.5 | JDK 21 + apt Maven |
| `pytest-junitxml` | Python 3.10+ | `pytest 6.0+` | Python 3.14.4 / pytest 9.0.3 | Python 3.10/3.12 + pytest 6+ |
| `jest-junit` | Node 18+ | `jest 29+` + `jest-junit 16+` | Node 25.8.2 / jest 29.7.0 / jest-junit 16.0.0 | Node 20 |
| `cargo-test-junit` | Rust stable 1.70+ | `cargo2junit` master | Rust 1.83 / cargo2junit 0.1.x | dtolnay/rust-toolchain@stable |

**关键发现**：5 个 pipe 在 Linux + macOS 平台全实测通过；Windows 仅 pytest-junitxml
在 CI 实测，其他 4 个 pipe 工具链在 Windows 装机复杂，**v3.4 留作 stretch**。

---

## 2. 各 pipe 详细矩阵

### 2.1 `go-test-json-to-junit`

| 维度 | 最低 | 实测 | 备注 |
|---|---|---|---|
| Go | **1.21** | 1.22（CI） / 1.26.3（mac） | 1.21 引入 `go test -json` 稳定输出格式 |
| go-junit-report | **v2.0.0** | v2.1.0 | v1 与 v2 输出 XML 格式**不同**（见 gotcha） |
| 平台 | macOS / Linux / Windows | macOS + Linux | Windows 未在 CI 验证（go-junit-report 跨平台理论 OK） |

#### Gotcha
- **v1 vs v2 默认 suite.name 行为不同**：v2 默认 `<testsuite name="">` 为空，
  需 fallback 从 `<system-out>` 内嵌的 JSON events 提取 Package（AISE 已内置 fallback 解析）
- **`-set-exit-code` 让 junit_proc 继承测试失败**：spawn 进程 returncode 不
  等价 pipeline 健康度，AISE 用 "XML 落盘 + 可解析" 判定 pipeline OK
- **`go test -v -json`** 比 `go test -json` 信息更全（Package 字段更完整），推荐用 -v

#### 安装
```bash
# macOS / Linux / Windows 统一
go install github.com/jstemmer/go-junit-report/v2@latest
# 装到 $GOPATH/bin（默认 ~/go/bin），需加 PATH
```

#### 升级注意
- v1 → v2：XML 元素顺序与 attrib 命名不变，但 testsuite.name 行为不同；AISE 已兼容
- Go 1.20 → 1.21：`go test -json` 字段稳定化，<1.21 可能有 Package 字段缺失

---

### 2.2 `mvn-surefire`

| 维度 | 最低 | 实测 | 备注 |
|---|---|---|---|
| JDK | **11** | 21（CI） / 26（mac） | 8 也能跑但 Surefire 3.x 推荐 11+ |
| Maven | **3.6.0** | 3.9.9 | 3.6.0 引入 `.mvn/maven.config` 标准化 |
| maven-surefire-plugin | **3.2.0** | 3.2.5 | 3.2.0 改进 JUnit 5 集成；2.x 也可工作但推荐升 |
| JUnit | **5.8** | 5.10.2 | 4.x 也支持（surefire 自动检测）|
| 平台 | Linux ✅ / mac ⚠️ / Windows ⚠️ | Linux + mac | mvn 慢 + 启动时间高，CI 仅 Linux 跑 |

#### Gotcha
- **企业内网 nexus 必须 override**：用户 `~/.m2/settings.xml` 可能指内网 mirror
  外网解析不了。AISE fixture 用 `.mvn/maven.config` + `.mvn/settings.xml`
  指向阿里云镜像，**推荐用户项目同样做**
- **Java 26 + Maven 3.9.9 触发 jansi/guava restricted method warning**：
  不影响功能但 stderr 含 warning。可忽略，未来 Maven 4 应解决
- **mvn-surefire 启动慢**（30-60s 含依赖解析 + JVM 启动）；生产应考虑 daemon
  模式（`mvnd`）或预编译
- **Surefire vs Failsafe 同名 testcase**：AISE collector 给 failsafe 加前缀避撞
- **`-DforceFail=true` 系统属性透传**：要求 pom.xml `<systemPropertyVariables>` 显式配置

#### 安装
```bash
# macOS
brew install maven
# Linux
apt install maven  # 或 sdkman install maven 拿新版
# Windows
winget install Apache.Maven  # 或 choco install maven
```

#### 升级注意
- maven-surefire 2.x → 3.x：JUnit 5 引擎自动加载，需检查 pom.xml provider 配置
- Maven 3.6 → 3.9：`.mvn/maven.config` 行为不变；新增 `--no-transfer-progress` 默认行为变化

---

### 2.3 `pytest-junitxml`

| 维度 | 最低 | 实测 | 备注 |
|---|---|---|---|
| Python | **3.10** | 3.14.4（mac） / 3.10 + 3.12（CI） | AISE 自身要求 3.10+ |
| pytest | **6.0** | 9.0.3 | 6.0 起 `--junit-xml` 稳定输出 |
| 平台 | macOS / Linux / Windows | **三平台 CI 全过** | Spike-3 唯一三平台验证的 pipe |

#### Gotcha
- **pip --user 装的 pytest 不在 PATH**：preflight_pipe 必须 fallback 到
  `python -m pytest`（AISE 已支持 alt_bins 机制）
- **`classname` 含模块路径**：`tests.test_calc.TestCalc`（含类）或
  `tests.test_calc`（模块函数）；AISE 用 `classname.rsplit('.', 1)[0]` 取
  parent_package
- **Windows 编码**：默认 cp1252 + 中文测试名 → JUnit XML 可能乱码；
  **强烈推荐 `PYTHONUTF8=1`**

#### 安装
```bash
# macOS / Linux
pip3 install --user pytest
# Windows
pip install --user pytest
# 或 venv：
python3 -m venv .venv && .venv/bin/pip install pytest
```

#### 升级注意
- pytest 7 → 8：`pytest.ini` 配置 deprecation；`--junit-xml` 接口不变
- pytest 8 → 9：collector 行为变化，但 `--junit-xml` 输出格式不变
- Python 3.9 → 3.10：`match` 语句、`Union` 类型注解推荐改写；AISE 不强制

---

### 2.4 `jest-junit`

| 维度 | 最低 | 实测 | 备注 |
|---|---|---|---|
| Node.js | **18** | 25.8.2（mac） / 20（CI） | jest 29 起 ESM + Node 18+ |
| jest | **29.0.0** | 29.7.0 | 28 reporter 接口与 29 有 minor 差异 |
| jest-junit | **16.0.0** | 16.0.0 | 14/15 输出格式略不同 |
| 平台 | macOS / Linux | macOS + Linux | Windows 未 CI（npm install jest 慢 + 路径分隔符）|

#### Gotcha
- **jest 在 fixture 内 `./node_modules/.bin/jest`**：不在系统 PATH。AISE
  PIPE_DEFS.runtime_bin = `"./node_modules/.bin/jest"`，preflight bin = `"node"`
- **`jest-junit` 必须在 `package.json` 的 `jest.reporters` 数组中配置**：
  CLI flag `--reporters=jest-junit` 在 Jest 29+ 不推荐；AISE fixture 用
  `package.json` 内置 reporter 配置
- **`JEST_JUNIT_OUTPUT_DIR` + `JEST_JUNIT_OUTPUT_NAME` 环境变量**：jest-junit
  从 env 取输出路径；AISE runner 通过 env 注入到 spawn 进程
- **`describe` block 嵌套时 classname 拼接**：jest-junit 默认 `classname` =
  `"<describe> <test_name>"`，name = `<test_name>`；AISE 用 testsuite.name
  做 parent_package

#### 安装
```bash
# 系统：装 Node
brew install node                              # macOS
apt install nodejs npm                         # Linux
winget install OpenJS.NodeJS                   # Windows

# 项目内（推荐）：
cd <project> && npm install --save-dev jest jest-junit
```

#### 升级注意
- jest 28 → 29：`testEnvironment` 默认从 jsdom 改 node；ESM 支持改善
- jest 29 → 30（预览）：reporter API 重构，jest-junit 16 应能继续工作
- Node 18 → 20 → LTS：ESM / Web Streams 默认开启

---

### 2.5 `cargo-test-junit`

| 维度 | 最低 | 实测 | 备注 |
|---|---|---|---|
| Rust | **stable 1.70** | 1.83（mac，2026 stable） | 1.70 起 `--report-time` 稳定 |
| cargo | 同 Rust toolchain | 同上 | stable 即可 |
| cargo2junit | **master**（无 release）| 当前 cargo install 版 | 上游无 semver 发布 |
| 平台 | macOS / Linux | macOS + Linux | Windows 未 CI（rustup 慢 + cargo2junit 安装）|

#### Gotcha
- **`cargo test --format json` 是 nightly-only**：stable Rust 不允许 `-Z
  unstable-options`；AISE 用 `RUSTC_BOOTSTRAP=1` env 绕开。完整风险评估
  与替代方案见 [`rustc-bootstrap-risk.md`](rustc-bootstrap-risk.md)
- **cargo stdout 混编译信息**：`Compiling` / `Finished` / `Running unittests`
  非 JSON 行会让 cargo2junit 解析失败；AISE 过滤纯 `{...}` 开头/结尾行
- **cargo2junit 对空 stdin 返回空 `<testsuites/>`**：看似成功但 actual_targets=[]；
  AISE 用 pipeline_ok = (len(collected) > 0) 兜底
- **classname = Rust 模块路径**（"tests" / "tests::sub" 等）：AISE 直接用
  classname 作 parent_package，与 Go/Maven 风格一致

#### 安装
```bash
# 装 Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal

# 装 cargo2junit
cargo install cargo2junit
# 默认装到 ~/.cargo/bin/cargo2junit
```

#### 升级注意
- **RUSTC_BOOTSTRAP=1 风险**：上游 Rust 未来可能改变 `-Z unstable-options` 语义。
  v3.4+ 应监控 Rust nightly 路线，必要时切换到 `cargo nextest`（输出 JUnit 原生）
- cargo nextest 是更现代替代：`cargo install nextest-cargo` + `cargo nextest run --message-format junit`，
  AISE v4 路线图考虑增加 `cargo-nextest-junit` 作为第 6 个 pipe
- Rust edition 2024 不影响 cargo test 输出格式

---

## 3. Spike 实测组合

| Spike | 平台 | 工具链组合 | 结果 |
|---|---|---|:---:|
| Spike-1 (Go) | mac (APFS) | Go 1.26.3 + go-junit-report v2.1.0 | ✅ 6 用例 |
| Spike-2 (mvn) | mac (APFS) | JDK 26 + Maven 3.9.9 + Surefire 3.2.5 | ✅ 6 用例 / 7m37s |
| Spike-3 (pytest) | mac (APFS) | Python 3.14.4 + pytest 9.0.3 | ✅ 5 用例 |
| Spike-3 (jest) | mac (APFS) | Node 25.8.2 + jest 29.7.0 + jest-junit 16.0.0 | ✅ 4 用例 |
| Spike-3 (cargo) | mac (APFS) | Rust 1.83 + cargo2junit master | ✅ 3 用例 |

## 4. GitHub Actions CI 矩阵实测

| Workflow | 触发 | 工具 | 结果 |
|---|---|---|:---:|
| #1-#7 | 各 commit push | 同上 + ubuntu/windows + Python 3.10/3.12 | 6/7 全过；#3 Windows UTF-8 fix 后通过 |

详见 `docs/v3.3-completion-report.md` §5。

---

## 5. 已知未验证版本

按风险优先级：

| 工具 | 未验证版本 | 风险 | 建议 |
|---|---|:---:|---|
| go-junit-report **v1** | v1.0.x | 中 | v1/v2 XML 格式不同；建议升级到 v2 |
| Maven **2.x** | 2.0.x / 2.1.x | 高 | Maven 2.x 不支持 .mvn/maven.config，AISE fixture 跑不通 |
| pytest **< 6.0** | 4.x / 5.x | 中 | `--junit-xml` 接口在 5.x 行为略不同（attribute 缺失）|
| jest **28.x** | 28.0.0 | 中 | reporter API 与 29 minor 不同；jest-junit 16 应仍能用 |
| jest-junit **< 16** | 14/15 | 中 | XML 输出 attribute 命名不同 |
| Rust **< 1.70** | 1.60-1.69 | 中 | `--report-time` 不稳定；可能输出格式差异 |
| Java **< 11** | 8/9/10 | 中 | Surefire 3.x 标 11+ 但实测 8 多数能跑 |
| Node **< 18** | 16/14 | 中 | jest 29 要求 18+，可能 jest fail to load |

---

## 6. 升级路径建议

### 5 pipe runner 全集升级
1. **保守路径**（生产环境）：锁定 Spike 实测版本，CI 拷贝同样版本
2. **激进路径**（新项目）：用各工具 latest，AISE preflight + doctor 会探测兼容性
3. **混合路径**（开发 / 测试分流）：dev 跑 latest，prod 锁版本

### AISE 自身升级
- `aise_doctor.py`（v3.4 已落地）随时检测当前环境是否满足最低版本
- 未来 `aise_doctor --check-versions` 子命令将比对版本号与本矩阵（v3.5 路线图）

---

## 7. 反馈

发现新组合 / 边界 bug，欢迎在 GitHub Issue 报告：
[https://github.com/heresun/AISE/issues](https://github.com/heresun/AISE/issues)

格式建议：
```
Pipe: cargo-test-junit
工具：Rust 1.65 + cargo2junit 0.1.7
平台：Ubuntu 22.04
现象：cargo2junit 对 -Z unstable-options 报 unknown flag
怀疑：Rust 1.70 之前对 -Z 选项限制更严
```

---

_本矩阵由 AISE 团队维护。v3.4 P1 兼容性矩阵 v1.0。_
