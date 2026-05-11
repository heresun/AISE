# AISE — Claude Code 插件

> **AISE 过程增强审查机制 v2**：端到端任务流程编排，覆盖大小模型分工、TDD 前置、多 persona 审查、智能熔断、知识沉淀闭环

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Cross-platform](https://img.shields.io/badge/platform-Win%20%7C%20Linux%20%7C%20macOS-blue)](#跨平台)

## ✨ 特性

| # | 优化点 | 实现方式 |
|---|--------|---------|
| ① | 客观验证硬门禁 | `aise_verify.py` 自动跑 test/lint，未通过强制回退 |
| ② | 多 Persona 并行审查 | `aise-ce-review` 调度 5 个 reviewer 并行 |
| ③ | TDD 前置 | `aise-test-driven-development` 强制 Red→Green→Refactor |
| ④ | DAG 任务分割 | `aise-planning-with-files` 输出依赖图 + 成本预估 |
| ⑤ | 智能熔断 | 错误模式识别（重复 / token / 爆炸半径） |
| ⑥ | Clean-room 审查 | SubAgent 隔离上下文，每个 reviewer 独立 worktree |
| ⑦ | 知识沉淀闭环 | `aise-ce-compound` + `aise_sediment.py` 自动回流 |
| ⑧ | 用户对齐 Checkpoint | 强制 EnterPlanMode 卡点 |
| ⑨ | 结构化上下文注入 | SessionStart hook 自动注入相关 patterns |
| ⑩ | 双轨监控 | metrics.jsonl + 健康度仪表盘 |

## 🚀 快速开始

### 安装

#### 方式一：从市场添加

```
/plugin marketplace add https://github.com/focus-tech/aise
/plugin install aise@aise
```

#### 方式二：本地开发安装

```bash
# 把本目录链接到 Claude Code 插件市场
git clone https://github.com/focus-tech/aise ~/.claude/plugins/marketplaces/aise
```

然后在 `~/.claude/settings.json` 的 `enabledPlugins` 中加入：

```json
{
  "enabledPlugins": {
    "aise@aise": true
  }
}
```

### 使用

```
/aise 给 data-bank 增加批量导出功能
```

整个流程会按 9 阶段串行/并行执行，全程跨平台。

### 手动调用脚本（可选）

```bash
# 初始化项目 .aise/
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_init.py"

# 沉淀一条 pattern
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_sediment.py" \
  --title "Oracle IN 子句分批处理" \
  --body "每批 500 条，留安全余量..." \
  --tags oracle batch \
  --global

# 查看健康度
python "${CLAUDE_PLUGIN_ROOT}/scripts/aise_dashboard.py"
```

## 📦 包含内容

```
aise/
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── commands/
│   └── aise.md                       # /aise slash command
├── skills/                           # 6 个内置 Skill（来自第三方插件复制，加 aise- 前缀）
│   ├── aise-brainstorming/           # ← from superpowers
│   ├── aise-test-driven-development/ # ← from superpowers
│   ├── aise-verification-before-completion/ # ← from superpowers
│   ├── aise-planning-with-files/     # ← from planning-with-files
│   ├── aise-ce-review/               # ← from compound-engineering
│   └── aise-ce-compound/             # ← from compound-engineering
├── scripts/                          # 7 个跨平台 Python 脚本
│   ├── aise_init.py
│   ├── aise_verify.py
│   ├── aise_track.py
│   ├── aise_fuse.py
│   ├── aise_inject_context.py
│   ├── aise_sediment.py
│   └── aise_dashboard.py
├── templates/aise/                   # .aise/ 工作区模板
├── hooks/
│   └── hooks.json                    # PostToolUse + SessionStart 自动注册
├── docs/
│   └── aise-guide.md                 # 完整实施指南
├── LICENSE
└── README.md
```

## 🌐 跨平台

- **Python 3.8+**，零外部依赖（仅标准库）
- **Windows / Linux / macOS** 全部支持
- 路径处理：`pathlib.Path`
- 进程调用：`subprocess`
- 编码：全部 `UTF-8`

> **Linux/macOS 用户**：若系统 Python 命令为 `python3`，请把插件 `hooks/hooks.json` 中的 `python` 改成 `python3`

## 🔁 与现有插件共存

本插件的 6 个 Skill 都是原插件的**重命名副本**（加 `aise-` 前缀），不会与原插件冲突：

- 安装 superpowers + aise → 同时拥有 `test-driven-development` 和 `aise-test-driven-development`，两者独立运行
- 卸载 superpowers / planning-with-files / compound-engineering 后，AISE 仍可单独工作

## 📋 配置项

### 自定义熔断阈值

`aise_fuse.py` 支持调参：

```bash
python aise_fuse.py \
  --repeat-threshold 3 \    # 同类错误重复阈值
  --token-budget 300000 \   # token 预算
  --blast-radius 20         # 文件改动数上限
```

### 自定义审查 Persona

编辑项目内 `.aise/review-config.md` 决定激活哪些 reviewer。

## 🛠️ 工作流总览

```
[文档产出] → [用户对齐✓] → [任务分割+DAG]
    ↓
[并行 SubAgent 组]
    ↓
[TDD: Red→Green→Refactor]
    ↓
[客观验证: 测试+Lint+类型]      ← 硬门禁
    ↓
[多 persona 并行审查]            ← 软门禁
    ↓
[模式识别熔断] → 通过?
    ├─ 是 → 标记完成 → 沉淀 patterns
    └─ 否 → 根因分析 → 重试 or 求助用户
```

详见 [docs/aise-guide.md](docs/aise-guide.md)。

## 📜 许可证

MIT — 详见 [LICENSE](LICENSE)。

第三方 Skill 来源声明：见 LICENSE 文件末尾的 Third-party Skill Attribution 段。

## 🙋 反馈与贡献

欢迎 Issue / PR / 经验分享～
