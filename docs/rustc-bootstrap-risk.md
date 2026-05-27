# RUSTC_BOOTSTRAP=1 风险评估（v3.4 P2-2）

> 评估 `cargo-test-junit` pipe 中使用 `RUSTC_BOOTSTRAP=1` 启用
> `-Z unstable-options` 的安全 / 兼容性风险，以及推荐的缓解措施和
> 长期替代方案。

---

## 1. 当前使用情况

`scripts/aise_event.py` 的 `run_cargo_pipe()`：

```python
cargo_cmd = [cargo_bin, "test", "--no-fail-fast", "--",
             "-Z", "unstable-options", "--format", "json", "--report-time"]

env = os.environ.copy()
env["RUSTC_BOOTSTRAP"] = "1"  # stable toolchain 启用 unstable -Z

cargo_proc = subprocess.run(cargo_cmd, env=env, ...)
```

为什么需要：
- `cargo test --format json` 是 **nightly-only** feature
- stable Rust 拒绝 `-Z unstable-options`（报 `error: the -Z flag is only
  accepted on the nightly channel of Cargo`）
- `RUSTC_BOOTSTRAP=1` 是 rustc/cargo **内部测试用的逃生口**，允许 stable
  toolchain 绕过 nightly 限制

---

## 2. 上游官方态度

Rust 项目明确不推荐在生产/普通用户场景使用 `RUSTC_BOOTSTRAP=1`：

> "This environment variable is only intended for use by Rust developers
> compiling rustc itself. Setting it disables important guarantees..."
>
> — Rust unstable-book / 多次 GitHub Issue 讨论

主要担忧：
1. **不稳定特性可能在任何 Rust 版本被改变或移除**
2. **绕过 stable / nightly 隔离机制**：stable 用户本来不该接触 unstable 行为
3. **代码中的 `#![feature(...)]` 也会被一起启用**：如果项目源码或依赖含 nightly 特性声明，会被无意激活
4. **CI / 工具链兼容性问题**：rustup 工具链切换可能行为异常

---

## 3. AISE 场景下的实际风险（按严重度）

### 🟢 低风险（实际场景）
- **`cargo test --format json` 输出格式**：实际上已稳定多年，被
  `cargo-nextest` / `cargo2junit` 等工具广泛依赖；Rust 团队几乎不可能
  以打破兼容的方式改它（会破坏整个生态）
- **AISE 仅在 cargo test 流程使用**，不影响生产构建（build / release）
- **stable Rust 工具链版本**：1.70+ 该行为稳定一致

### 🟡 中风险
- **未来 Rust 版本可能强化 `RUSTC_BOOTSTRAP` 检查**：例如要求
  `RUSTC_BOOTSTRAP=<crate-name>` 形式（已在某些 RFC 讨论中）；如果
  生效，AISE 当前简单 `=1` 写法可能失效
- **依赖代码含 `#![feature(...)]` 时连带启用**：用户项目如果依赖了
  某些 crate（特别是底层库），可能被无意启用 nightly 特性，导致编译
  行为与纯 stable 不同
- **`-Z report-time` 在不同 Rust 版本输出微差异**：JSON 字段 `exec_time`
  在 1.70 之前可能缺失或精度不同

### 🟠 偏高风险（理论）
- **CVE / 安全公告**：如果未来发现某 unstable 特性有内存安全 / 沙箱逃逸
  漏洞，启用了 `RUSTC_BOOTSTRAP=1` 的 AISE 用户会比纯 stable 用户多一份
  风险（即使该 unstable feature 用户没显式启用，因为编译器内部检查会
  被绕过）
- **审计 / 合规**：在金融、医疗等强合规场景，"用 nightly 特性的工具
  跑测试"可能触发审计警告

### 🔴 高风险（仅理论，AISE 场景几乎不可能触发）
- **`-Z` 路径外其他副作用**：cargo 内部代码路径可能在 RUSTC_BOOTSTRAP
  下走不同分支，理论上有"测试环境与生产环境编译行为不一致"的可能；
  实际上 AISE 仅做 `cargo test`，build artifact 一次性的，不影响发布
  二进制

---

## 4. 缓解措施（当前 v3.4）

### 4.1 文档化警告（已落地）
- `docs/spike-3-summary.md` §4 工程发现已列出 `RUSTC_BOOTSTRAP=1`
- `docs/tool-compatibility-matrix.md` §2.5 cargo gotcha 明确说明
- 本文档（`docs/rustc-bootstrap-risk.md`）专门评估

### 4.2 不在生产构建路径使用（设计上保证）
- AISE `aise_event.py` 的 `RUSTC_BOOTSTRAP=1` 仅设在 cargo test 子进程
  的 env 中
- 不影响调用方 shell / 用户其他 cargo 命令
- 不写入用户 `~/.bashrc` / `~/.cargo/config.toml`

### 4.3 让用户可选退出（v3.5 路线图）
计划添加：
```bash
python aise_event.py --pipe cargo-test-junit --no-bootstrap-hack ...
```
关闭 `RUSTC_BOOTSTRAP=1` 后，cargo test 会因 `-Z` 失败 → 此时用户必须
使用替代 pipe（见 §5）。

---

## 5. 长期替代方案

### 5.1 `cargo-nextest`（**强烈推荐**，v3.5 计划实现）

```bash
cargo install cargo-nextest --locked
cargo nextest run --message-format=junit  # 原生 JUnit 输出，无需 -Z
```

优势：
- ✅ **原生 JUnit XML 输出**，不需要 cargo2junit 中转
- ✅ **更快**：并行测试、独立进程隔离
- ✅ **stable Rust 即可**，不需要 `RUSTC_BOOTSTRAP=1`
- ✅ 维护活跃（matklad → nektosact 项目，企业级使用）
- ✅ 更好的 retry / partition / filter 等功能

劣势：
- ⚠️ 需要单独安装（不在 cargo 内置）
- ⚠️ 输出 XML 格式与 cargo2junit 略不同（AISE 解析器需调整）

v3.5 路线图：增加第 6 个 pipe **`cargo-nextest-junit`**，让用户二选一：
- `cargo-test-junit`：已有，RUSTC_BOOTSTRAP=1，无需额外装
- `cargo-nextest-junit`：新增，stable Rust + 装 cargo-nextest

### 5.2 等 cargo 把 `--format json` 稳定到 stable（被动等待）

跟踪 issue：
- [cargo#9151](https://github.com/rust-lang/cargo/issues/9151) — 讨论
  `cargo test` JSON output 稳定化（多年讨论中）

Rust 团队倾向是 cargo-nextest 替代旧 test runner，老路径稳定化优先级
不高。AISE 不应被动等待。

### 5.3 解析人类可读输出（不推荐）

```bash
cargo test  # 没 -Z 也能跑，但输出是人类可读 text
```

解析 `running 3 tests` / `test foo::bar ... ok` 等文本极其脆弱，
版本差异大，AISE 不采用。

### 5.4 第三方 cargo 子命令

如 `cargo-test-junit`（同名第三方 crate）、`cargo-jenkins-test` 等。
质量参差，维护活跃度不一，AISE 不依赖。

---

## 6. 决策与升级路径

### 当前（v3.4）
**保留 `RUSTC_BOOTSTRAP=1` + `-Z unstable-options`** 作为 cargo pipe 默认
实现。理由：
1. AISE 主路径是测试运行，不是发布构建，风险窗口窄
2. `cargo test --format json` 输出格式已稳定多年，破坏可能性低
3. 实测在 Rust 1.70+ 行为一致
4. 用户安装成本最低（不需额外装 nextest）
5. 已在多处文档明确警告

### v3.5（计划）
- 增加 `cargo-nextest-junit` 作为 **首选** pipe
- `cargo-test-junit` 降级为 **fallback**（当用户未装 nextest 时）
- `aise_doctor` 检测 cargo-nextest 是否安装，未装时建议用户装

### v3.6+（长期）
- 监控 Rust upstream `cargo test --format json` 稳定化进度
- 若 stable 化 → 全部切换到原生 stable，移除 RUSTC_BOOTSTRAP=1

---

## 7. 用户指引

如果你**不能接受** `RUSTC_BOOTSTRAP=1`（合规 / 安全审计 / 哲学原因）：

### 临时方案
1. 装 cargo-nextest：
   ```bash
   cargo install cargo-nextest --locked
   ```
2. 手动跑：
   ```bash
   cd <project>
   cargo nextest run --message-format=junit > junit.xml
   ```
3. AISE 当前不会自动用 nextest（v3.5 落地后即可）

### 等 v3.5
路线图见上。

---

## 8. 一句话结论

> AISE 在 stable Rust 启用 `RUSTC_BOOTSTRAP=1 -Z unstable-options` 是当前
> 最低摩擦的实现，**实际风险窗口窄、影响面小**，但**不应作为长期方案**。
> v3.5 路线图将引入 `cargo-nextest-junit` 作为首选 pipe，逐步淘汰
> RUSTC_BOOTSTRAP 路径。

---

## 9. 相关引用

- Rust unstable book: <https://doc.rust-lang.org/unstable-book/>
- cargo-nextest: <https://nexte.st/>
- cargo#9151（test JSON output 稳定化）: <https://github.com/rust-lang/cargo/issues/9151>
- v3.2.5 §20 已知未尽事项 §20 / spike-3-summary.md §4.4

---

_本评估由 AISE 团队生成。v3.4 P2-2
RUSTC_BOOTSTRAP 风险评估 v1.0。_
