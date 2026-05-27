# AISE 使用教程（v3.6.0）

> 从零到完整跑通 AISE 任务流程的 step-by-step 教程。10 分钟从安装到第一个
> 任务跑出 machine signoff。

---

## 🎯 这份教程适合谁

- **新用户**：刚装 Claude Code + AISE 插件，想知道怎么用
- **二次开发者**：想理解 plan.json schema、手动跑各 pipe runner
- **合规/安全审计**：想看 evidence.jsonl + plan.snapshot 防篡改实测

每节都有 **「✅ 验证产出」** 部分，按指引跑完即可确认成功。

---

## 🚨 关键说明：谁来跑这些脚本？

**用户只用 2 个 slash command**：

```
/aise <任务描述>      日常任务入口
/aise-doctor          环境自检 + 排查（AI 解析并给友好总结）
```

剩下全是 AI / 内部自动调，用户不需要记 Python 脚本路径：

| 入口 / 脚本 | 谁触发 | 何时 |
|---|---|---|
| `/aise <任务>` slash command | **👤 用户** | 日常任务入口 |
| `/aise-doctor` slash command | **👤 用户** | 装好后自检 + 排查 |
| `scripts/aise_doctor.py` | 🤖 AI（通过 `/aise-doctor`） | 由 AI 解析输出，给用户友好总结 |
| `scripts/aise_run_init.py` | 🤖 Claude Code 自动 | `/aise` 内 ExitPlanMode 后 |
| `scripts/aise_scope_check.py` | 🤖 Claude Code 自动 | worker commit 前 |
| `scripts/aise_event.py --pipe X` | 🤖 Claude Code 自动 | 跑测试时 |
| `scripts/aise_verify.py` | 🤖 Claude Code 自动 | gate 阶段 |
| `.aise/plan.json` 编辑 | 👤 用户 + 🤖 AI 协作 | ExitPlanMode 前 |

下面 **Step 0-2 / 7-8 是用户日常用的**，**Step 3-6 是二次开发 / debug / 学习
内部机制时手动跑** — 日常用户可以跳过。

---

## Step 0：环境检查（30 秒）

### 必装
- Python ≥ 3.10
- git

### 可选（按要跑的 pipe 选）
- Go ≥ 1.21 + `go-junit-report v2`（cargo pipe 用）
- JDK ≥ 11 + Maven ≥ 3.6（mvn pipe 用）
- pytest ≥ 6.0（pytest pipe 用）
- Node ≥ 18（jest pipe 用）
- Rust stable + `cargo-nextest`（推荐 Rust pipe）

### 用 /aise-doctor 一键自检（推荐）

在 Claude Code 直接输入：

```
/aise-doctor
```

AI 会跑底层 `aise_doctor.py` 并给你**人话总结**（不是 dump 原始 markdown）。
含：
- ✅ 基础环境（Python / git / AISE 内部模块）
- 📦 6 个 pipe runner 工具就绪状态
- 🌏 region 探测（CN 自动展示国内镜像建议）
- 📊 通过 / 警告 / 缺失计数 + 针对性建议

✅ 验证产出：终端看到友好总结，含具体「建议」段落。

完整 markdown 报告：`/aise-doctor --full`
导出到文件：`/aise-doctor --export ~/doctor.md`
CI 严格模式：`/aise-doctor --strict`

---

## Step 1：安装 AISE 插件（1 分钟）

### 方式一：从市场安装（推荐）

在 Claude Code 中：

```
/plugin marketplace add https://github.com/heresun/AISE
/plugin install aise@aise
```

### 方式二：本地开发安装

```bash
git clone https://github.com/heresun/AISE ~/.claude/plugins/marketplaces/aise
```

然后在 `~/.claude/settings.json` 启用：

```json
{
  "enabledPlugins": {
    "aise@aise": true
  }
}
```

✅ 验证产出：在 Claude Code 中输入 `/aise` 能看到 slash command 提示。

---

## Step 2：第一次跑 /aise（小白模式，2 分钟）

直接在 Claude Code 输入：

```
/aise 给我的项目加一个简单的 hello world 函数
```

AISE 主流程自动跑 9 个阶段：

1. **brainstorming**：理解需求
2. **requirements**：产出 acceptance criteria
3. **EnterPlanMode**：让你审查计划（**关键卡点**）
4. **ExitPlanMode 后自动调 aise_run_init.py**：plan 校验 + run_id 分配
5. **TDD 执行**：Red → Green → Refactor（SubAgent 隔离 worktree）
6. **aise_scope_check.py**：git diff 越界检查
7. **aise_event.py**：跑测试 + evidence 签收
8. **aise_verify.py --verify-evidence**：机器签收复核
9. **多 persona 审查 + patterns 沉淀**

✅ 验证产出：
- `.aise/` 目录建立
- `.aise/runs/<run_id>/run_context.json` 存在
- `.aise/runs/<run_id>/evidence.jsonl` 至少一行（含 sha256 + mtime）
- 项目内文件按 plan.json scope.paths 范围内
- git log 看到 worker commit

---

---

# 🛠️ 二次开发 / 调试章节（Step 3 - 6）

> ⚠️ **以下章节面向想理解 AISE 内部机制、做二次开发、合规审计的读者**。
> 日常用户只用 `/aise <任务>` + `aise_doctor.py`，可以直接跳到 Step 7。

---

## Step 3：写一个 plan.json（手动模式，5 分钟）

> 🤖 **正常 `/aise` 流程会自动产生 plan.json**（通过 aise-planning-with-files
> skill）。本节适用于：想跳过 brainstorming、精确控制 task 拆分、或单独测试
> aise_run_init 的人。

实际使用 AISE 主流程会自动产 `plan.json`。但你也可以手动写来精确控制：

### 创建 `.aise/plan.json`

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
        "targets": ["tests"]
      },
      "dependencies": [],
      "shared_evidence_tasks": []
    }
  ]
}
```

字段说明：
- `task_id`：唯一字符串（全局）
- `scope.paths`：glob 风格，相对项目根。**worker 改动必须在此范围内**
- `test_manifest.pipe`：6 选 1：
  - `go-test-json-to-junit` / `mvn-surefire` / `pytest-junitxml` /
    `jest-junit` / `cargo-test-junit` / `cargo-nextest-junit` ⭐
- `dependencies`：task_id 列表，按拓扑序执行
- `shared_evidence_tasks`：互相背书证据（v3.2.5 P1-C scope 必须相交）

完整 schema 见 [`plan-schema.md`](plan-schema.md)。

### 验证 plan.json

```bash
python ~/.claude/plugins/marketplaces/aise/scripts/aise_run_init.py \
    --project-root "$(pwd)"
```

✅ 验证产出：
```
[AISE-run-init] OK
  run_id:     20260519-...
  run_dir:    ./.aise/runs/<run_id>
  snapshot:   ./.aise/plan.snapshot.json  (sha256=...)
  tasks:      1
```

如果 plan 校验失败（如 scope 空 / pipe 拼错），会 exit 2 + 列出每个违规项。

---

## Step 4：手动跑各 pipe runner（10 分钟）

> 🤖 **正常 `/aise` 流程会按 plan.json 的 test_manifest.pipe 自动选 + 调用**。
> 本节适用于：debug pipe 行为 / 学 evidence 链路 / 在 CI 单独跑某 pipe。

### 4.1 跑 Go pipe（如果有 Go 项目）

```bash
python aise_event.py \
    --pipe go-test-json-to-junit \
    --project-root /path/to/go-project \
    --target ./pkg/... \
    --run-id manual-001
```

输出 JSON summary 含 `actual_test_targets[]`、`evidence_jsonl` 路径等。

### 4.2 跑 pytest pipe

```bash
python aise_event.py \
    --pipe pytest-junitxml \
    --project-root /path/to/python-project \
    --run-id manual-002
```

默认跑 `tests/` 目录。可加 `--pytest-extra-arg "-k test_specific"`。

### 4.3 跑 cargo-nextest pipe（Rust 推荐）⭐

先在 Rust 项目里加 `.config/nextest.toml`：

```toml
[profile.default.junit]
path = "junit.xml"
```

然后：

```bash
python aise_event.py \
    --pipe cargo-nextest-junit \
    --project-root /path/to/rust-project \
    --run-id manual-003
```

✅ 比 `cargo-test-junit` 快 60% + 不需要 `RUSTC_BOOTSTRAP=1`。

### 4.4 跑 mvn pipe（Java/Kotlin）

```bash
python aise_event.py \
    --pipe mvn-surefire \
    --project-root /path/to/maven-project \
    --run-id manual-004
```

如果用户的 `~/.m2/settings.xml` 指内网 nexus，需在项目 `.mvn/maven.config` +
`.mvn/settings.xml` 用阿里云镜像（参考 `tests/fixtures/maven-sample/.mvn/`）。

---

## Step 5：scope gate（worker commit 前）

> 🤖 **正常 `/aise` 流程在每个 task TDD 后自动调用**。本节适用于：在
> hook / pre-commit 单独触发 / 验证 scope 配置是否正确。

worker 改完代码后、commit 前**必须**跑：

```bash
python aise_scope_check.py \
    --project-root "$(pwd)" \
    --task-id "T-001"
```

✅ 验证产出：
- exit 0 → 所有 git diff 文件都在 `task.scope.paths` 内
- exit 1 → 列出越界文件
- exit 2 → run_context.json 缺 / plan.snapshot 被篡改 / task_id 未知

scope 越界示例：
```
[AISE-scope-check] FAIL  task=T-001
  scope.paths: ['src/calc/**', 'tests/test_calc*.py']
  越界文件 (2 个):
    - src/auth/login.py
    - README.md
```

---

## Step 6：evidence 复核（machine signoff）

> 🤖 **正常 `/aise` 流程在 gate 阶段自动调用 aise_verify.py**。本节用户
> 也可主动跑：合规审计 / 跨 session 续跑确认证据未篡改 / debug。

测试跑完后，任何时候都可复核 evidence：

```bash
python aise_verify.py --verify-evidence
```

它会：
1. 读 `.aise/runs/<latest>/evidence.jsonl`
2. 对每个 artifact 重算 sha256
3. 检查 mtime 仍在生成窗口（±2s 容忍）内
4. 任何不一致 → exit 1 + 列出违规

✅ 验证防篡改：
```bash
# 故意改一个 JUnit XML
echo "x" >> .aise/runs/<run_id>/test_reports/junit.xml

# 再复核
python aise_verify.py --verify-evidence
```

应该看到：
```
exit 1
violations:
  - evidence_tampered: actual_sha256 != expected
```

---

---

# 👤 用户日常使用章节（Step 7 - 9）

> 以下章节面向所有用户，是装好 AISE 后日常会用到的脚本。

---

## Step 7：用 /aise-doctor 排查问题（v3.4+）

> 用户日常诊断主入口，4 种模式 4 行命令搞定。

### 友好总结（推荐，默认）

```
/aise-doctor
```

AI 解析后给「人话总结」+ 针对性建议，不是 dump 原始 markdown。

### 完整 markdown 报告

```
/aise-doctor --full
```

含 6 大类 check 详细输出（Python / AISE 内部 / git / stdio / pipe / project）
+ 「🔢 版本检查」+ 「🌏 镜像建议」章节。

### 导出报告分享团队

```
/aise-doctor --export ~/doctor-report.md
```

写到指定文件，便于贴到 GitHub Issue 或 Slack。

### CI / 严格模式

```
/aise-doctor --strict
```

任何 fail 或 warn 都 fatal exit 2。CI 启动前预检用。

### 底层脚本（二次开发用）

如需直接调脚本（绕过 AI 解析），手动跑：

```bash
PYTHONUTF8=1 python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_doctor.py" --check-versions --json
```

CLI 参数透传（`--region` / `--export` / `--strict` / `--project-root`），
详见 `scripts/aise_doctor.py --help`。

---

## Step 8：故障排查（FAQ）

### Q1：`/aise` 命令不识别？

确认插件已启用：
```bash
cat ~/.claude/settings.json | grep aise
```
应该看到 `"aise@aise": true`。重启 Claude Code。

### Q2：Windows 跑出中文乱码？

设环境变量：
```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

或永久加到系统环境变量。

### Q3：mvn 拉不到依赖（企业内网）？

在项目根建 `.mvn/maven.config`：
```
-s
.mvn/settings.xml
```

`.mvn/settings.xml` 指阿里云：
```xml
<settings>
  <mirrors>
    <mirror>
      <id>aliyunmaven</id>
      <mirrorOf>*</mirrorOf>
      <url>https://maven.aliyun.com/repository/public</url>
    </mirror>
  </mirrors>
</settings>
```

### Q4：cargo 测试报 "-Z unstable-options is unstable"？

两个选择：
- **临时**：`cargo-test-junit` pipe 会自动设 `RUSTC_BOOTSTRAP=1`，但有
  [安全风险](rustc-bootstrap-risk.md)
- **推荐**：换用 `cargo-nextest-junit` pipe（v3.5+，stable Rust 原生支持）

### Q5：evidence_tampered 误报？

通常是：
1. IDE 自动 reformat XML（编辑器破坏内容）
2. 跨 NFS / SMB 网络盘跑测试（mtime 不准）
3. 真的有篡改

排查：
```bash
# 看 evidence.jsonl 记录的 sha 与实际
python -c "
import hashlib, json
ev = json.loads(open('.aise/runs/<run_id>/evidence.jsonl').readline())
actual = hashlib.sha256(open(ev['artifact_path'], 'rb').read()).hexdigest()
print(f'expected: {ev[\"sha256\"]}')
print(f'actual:   {actual}')
"
```

### Q6：jest 报 `Cannot find module 'jest-junit'`？

在 fixture 项目内装：
```bash
cd <project> && npm install --save-dev jest jest-junit
```

并在 `package.json` 配置 reporters：
```json
{
  "jest": {
    "reporters": [
      "default",
      ["jest-junit", {"outputDirectory": ".", "outputName": "junit.xml"}]
    ]
  }
}
```

参考 `tests/fixtures/jest-sample/package.json`。

### Q7：本地全过但 CI fail？

v3.3 P0-2/3 实测的几个 Windows 边界：
1. **路径分隔符**：v3.3 `defense_in_depth_check` 已自动归一 `\` → `/`
2. **pid 探测**：v3.3 用 ctypes 调 kernel32 STILL_ACTIVE
3. **stdio 编码**：必须 PYTHONUTF8=1（CI workflow 已配置）

确认 `.github/workflows/test.yml` 顶级有：
```yaml
env:
  PYTHONUTF8: "1"
  PYTHONIOENCODING: "utf-8"
```

---

## Step 9：进阶 — 自定义白名单

### 自定义 pipe 的 allowed_patterns

```bash
python aise_event.py \
    --pipe pytest-junitxml \
    --project-root . \
    --allowed-pattern "my_tests/**" \
    --allowed-pattern "integration/**" \
    --target "my_tests"
```

如果 `--target` 不命中 `--allowed-pattern`，spawn 前防御深度二次校验拦截，
exit 2。

### 自定义 mtime 容忍

在 plan.json 顶级加：

```json
{
  "scope_policy": {
    "mtime_window_tolerance_ms": 5000
  }
}
```

适用于 mtime 精度差的文件系统（如 NFS / FAT32）。

---

## 📚 进一步阅读

| 文档 | 内容 |
|---|---|
| [`architecture.md`](architecture.md) | Mermaid 架构图（5 层 + 三阶段 + 数据流）|
| [`plan-schema.md`](plan-schema.md) | plan.json schema v1.0 完整定义 |
| [`tool-compatibility-matrix.md`](tool-compatibility-matrix.md) | 6 pipe × 工具版本支持矩阵 |
| [`rustc-bootstrap-risk.md`](rustc-bootstrap-risk.md) | cargo-test 安全风险 + nextest 替代方案 |
| [`spike-2-compatibility.md`](spike-2-compatibility.md) | 跨平台兼容性报告 |
| [`v3.4-6-completion-report.md`](v3.4-6-completion-report.md) | v3.6.0 完成度报告 |
| [`../AGENTS.md`](../AGENTS.md) | 项目级 AI onboarding（13+ 个工程踩坑）|
| [`../CHANGELOG.md`](../CHANGELOG.md) | v3.3.0 / v3.5.0 / v3.6.0 release notes |

---

## 🚀 一句话总结

### 用户日常（95% 场景）
> 1. 装好 → 输入 `/aise-doctor` 自检环境
> 2. 在 Claude Code 输入 `/aise <任务描述>`
> 3. EnterPlanMode 时审查 + 调整计划，ExitPlanMode 批准
> 4. 等 Claude Code 自动完成 9 阶段 → 看 git log + 测试报告
> 5. 出问题 → 再跑 `/aise-doctor` 看 AI 总结哪里有问题

### 内部机制（二次开发 / 合规审计）
> `aise_run_init.py` → worker TDD → `aise_scope_check.py` → `aise_event.py
> --pipe X` → `aise_verify.py --verify-evidence`。完整闭环，机器签收，
> 跨平台 CI 实测。
>
> **关键 = 通过判定基于机器签收（sha256 + mtime + 生成窗口），不信 Agent 自报。**

---

_本教程由 AISE 团队维护。v3.6.0。_
