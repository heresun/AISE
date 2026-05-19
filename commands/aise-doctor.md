---
description: AISE 环境自检 - 一键诊断 6 pipe 工具链 / 跨平台 / 镜像 / 版本兼容性
allowed-tools: Read, Bash, Write
---

# /aise-doctor — AISE 环境自检

## 用途

一键扫描用户当前 AISE 运行环境，给出友好的总结报告：
- Python / git 等基础工具是否就绪
- 6 个 pipe runner（go / mvn / pytest / jest / cargo / cargo-nextest）哪些可用
- stdio 编码 / 跨平台兼容性（Windows UTF-8 等）
- region 探测 + 国内镜像建议（CN 用户自动展示）
- 工具版本是否满足 [`tool-compatibility-matrix.md`](../docs/tool-compatibility-matrix.md) 最低要求

## 用户输入

```
/aise-doctor                  # 友好总结（推荐，默认）
/aise-doctor --full           # 完整 markdown 报告
/aise-doctor --export <path>  # 导出报告到文件（便于分享团队）
/aise-doctor --strict         # 任何 fail 都 fatal（CI 用）
```

## 执行流程（AI 按此执行）

### 步骤 1：跑底层 doctor 脚本

```bash
PYTHONUTF8=1 python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_doctor.py" --check-versions --json
```

⚠️ 注意：
- 必须设 `PYTHONUTF8=1` 避免 Windows cp1252 解码失败
- `--json` 拿机器可读结构便于解析
- `--check-versions` 同时跑版本对比

### 步骤 2：解析 JSON 输出

JSON 结构（参考 `scripts/aise_doctor.py` `--json` 模式）：
```json
{
  "checks": [
    {"category": "python|aise_internal|git|stdio_encoding|pipe_tools|project",
     "name": "...", "status": "ok|warn|fail",
     "detail": "...", "install_hint": "..."}
  ],
  "summary": {"total": N, "ok": N, "warn": N, "fail": N, "exit_code": N},
  "region": {"detected": "cn|us|global", "source": "env_var|timezone|...",
             "timezone": "Asia/Shanghai"},
  "mirrors": {"brew": {...}, "maven": {...}, ...},
  "version_checks": [
    {"tool": "go", "status": "ok|warn|skip|fail",
     "actual": "1.26.3", "min_version": "1.21.0"}
  ]
}
```

### 步骤 3：给用户友好总结

**默认模式**（不带 `--full`）：

按以下格式输出，**不要 dump 原始 JSON / markdown**：

```
🩺 AISE 环境自检报告

✅ 基础环境：Python 3.x / git / AISE 内部模块全部就绪
⚠️ stdio 编码：建议设 PYTHONUTF8=1（已在 CI 配置，本地交互可选）

📦 6 个 pipe runner 工具：
  ✅ go-test-json-to-junit   (go 1.x.x ≥ 1.21)
  ❌ mvn-surefire             未装 → brew install maven
  ✅ pytest-junitxml          (pytest 9.x ≥ 6)
  ⏸️ jest-junit               未装（仅 JS 项目需要）
  ✅ cargo-test-junit         (cargo 1.x ≥ 1.70)
  ⭐ cargo-nextest-junit      (推荐 Rust 用，需 cargo install cargo-nextest)

🌏 region: cn（timezone 探测） → 国内镜像建议 5 项
  · brew → mirrors.ustc.edu.cn
  · maven → maven.aliyun.com
  · pip → mirrors.aliyun.com
  · npm → registry.npmmirror.com
  · cargo → mirrors.ustc.edu.cn

📊 总结：N 项通过 / N 项警告 / N 项缺失
```

并根据具体情况给**针对性建议**：
- 如果有 fail：给出 1-3 条最优先要装的工具 + 一行安装命令
- 如果版本过低：明确说"X 版本 N.N.N 低于推荐 M.M.M，建议升级"
- 如果 region=cn 且镜像 fail：建议运行 setup_command
- 如果全 ✅：用 1 句话说"环境就绪，可以跑 /aise 任务"

### 步骤 4：可选 — 导出报告

如果用户带 `--export <path>` 参数：

```bash
PYTHONUTF8=1 python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_doctor.py" \
    --check-versions --export "<path>"
```

报告会写到指定路径（markdown 格式），同时 stdout 也输出。

### 步骤 5：可选 — 完整报告

如果用户带 `--full` 参数，**不要友好总结**，直接 cat markdown：

```bash
PYTHONUTF8=1 python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_doctor.py" --check-versions
```

把脚本输出原样转发给用户（含「🔢 版本检查」「🌏 镜像建议」等章节）。

### 步骤 6：strict 模式

如果用户带 `--strict`：

```bash
PYTHONUTF8=1 python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_doctor.py" \
    --check-versions --strict --json
```

任何 fail 或 warn 都会 exit 2。CI 场景用。AI 接到 exit code 后提示用户。

## 退出码处理

| exit code | 含义 | AI 应该做什么 |
|:---:|---|---|
| 0 | 全 ok | 给用户绿色 ✅ 总结 |
| 1 | 仅 optional 缺失（如 pipe 工具按需装）| 给用户温和提示，列出缺失工具 |
| 2 | 关键 fail（Python / AISE 内部 / git / stdio）| **明确警告**，不能跑 `/aise` 直到修 |
| 127 | （由 aise_doctor.py 内部不使用；预留）| — |

## 用户交互示例

### 场景 1：新用户首次跑

```
用户: /aise-doctor

AI: 🩺 AISE 环境自检报告

✅ Python 3.14.4 ≥ 3.10
✅ git 2.39.5
✅ AISE 内部 7 个 lib 模块全部就绪
⚠️ PYTHONUTF8 环境变量未设置（Windows 用户建议设置）

📦 Pipe Runner 工具:
  ✅ go-test-json-to-junit (go 1.26.3, go-junit-report 已装)
  ❌ mvn-surefire (未装)
  ✅ pytest-junitxml (via python3 -m pytest)
  ❌ jest-junit (node 未装)
  ❌ cargo-test-junit (cargo 未装)
  ❌ cargo-nextest-junit (cargo + nextest 未装)

📊 总结: 11 通过 / 1 警告 / 4 缺失

💡 建议:
- 如果你跑 Java 项目：brew install maven
- 如果你跑 Rust 项目：先装 Rust toolchain，再 cargo install cargo-nextest
- 如果你不用 mvn/jest/cargo，可忽略 ❌ 项（按需装）

你现在可以跑 `/aise <任务>` 启动主流程（Go + Python 项目无障碍）。
```

### 场景 2：CN 用户

```
用户: /aise-doctor

AI: 🩺 AISE 环境自检报告

...（同上）

🌏 检测到 region: cn（基于时区 Asia/Shanghai）

国内镜像建议（可加速依赖下载）:
1. brew → 设 HOMEBREW_BOTTLE_DOMAIN=https://mirrors.ustc.edu.cn/homebrew-bottles
2. maven → 项目内 .mvn/settings.xml 配阿里云镜像
3. pip → pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
（如需完整配置命令，跑 `/aise-doctor --full`）

📊 总结: ...
```

### 场景 3：CI 场景

```
用户: /aise-doctor --strict

AI: 跑 aise_doctor.py --strict --json...
exit code: 2

❌ FAIL — 关键工具缺失:
- mvn 未在 PATH 上（你的 plan.json 引用了 mvn-surefire pipe）

修复:
brew install maven   # macOS
apt install maven    # Linux

修复后重跑 /aise-doctor --strict 验证。
```

## 与 /aise 主流程的关系

- `/aise-doctor` 是**独立诊断工具**，不参与 9 阶段主流程
- 推荐在以下时机用：
  · 装完 AISE 插件第一次
  · `/aise` 出问题不知道哪里坏
  · 团队 onboarding 新成员
  · CI 启动前预检（`--strict` 模式）

## 实现说明（给二次开发者）

底层调用 `scripts/aise_doctor.py`（Python，零外部依赖）。脚本本身的
CLI 参数与本 slash command 透传：
- `--json` / `--full` 控制输出格式
- `--check-versions` 跑工具版本对比
- `--export <path>` 落盘报告
- `--strict` 严格模式
- `--region <cn|us|global>` 手动指定 region
- `--project-root <path>` 项目级 plan.json schema 校验

详见 [`scripts/aise_doctor.py`](../scripts/aise_doctor.py) 和
[`docs/aise-guide.md`](../docs/aise-guide.md) §6 调参指南。
