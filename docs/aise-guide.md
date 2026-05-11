# AISE 过程增强审查机制实施指南

> 对应 v2 设计图：`C:\Users\sundehui\Documents\AISE过程增强审查机制流程图_v2.drawio`
> 版本：v1.0
> 适用：Claude Code + Superpowers + Compound Engineering 插件环境

## 1. 整体架构

AISE v2 由三层组件构成：

| 层 | 组件 | 职责 |
|----|------|------|
| 编排层 | `/aise` slash command | 调度 9 个阶段，委托现成 Skill |
| 执行层 | Python 脚本 (`~/.claude/scripts/aise_*.py`) | 验证 / 熔断 / 注入 / 沉淀 / 监控 |
| 状态层 | 项目根目录 `.aise/` | 进度、计划、日志、patterns |

## 2. 文件清单

### 命令与文档
| 路径 | 用途 |
|------|------|
| `~/.claude/commands/aise.md` | `/aise` slash command 定义 |
| `~/.claude/docs/aise-guide.md` | 本文档 |
| `~/.claude/templates/aise/` | `.aise/` 工作区模板 |

### 脚本
| 路径 | 触发方式 | 用途 |
|------|---------|------|
| `aise_init.py` | `/aise` 步骤 0 主动调用 | 初始化项目 `.aise/` 目录 |
| `aise_verify.py` | `/aise` 步骤 5 主动调用 | 客观验证硬门禁 |
| `aise_track.py` | `PostToolUse` hook 自动 | 记录错误模式 |
| `aise_fuse.py` | `/aise` 步骤 7 主动调用 | 智能熔断判断 |
| `aise_inject_context.py` | `SessionStart` hook 自动 | 注入历史 patterns |
| `aise_sediment.py` | `/aise` 步骤 8 主动调用 | 沉淀 patterns |
| `aise_dashboard.py` | `/aise` 步骤 9 主动调用 | 生成健康度报表 |

### Hooks 配置（已写入 `~/.claude/settings.json`）

```json
{
  "hooks": {
    "PostToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [{"type":"command","command":"python ~/.claude/scripts/aise_track.py"}]}],
    "SessionStart": [{"matcher": "startup|resume|clear", "hooks": [{"type":"command","command":"python ~/.claude/scripts/aise_inject_context.py"}]}]
  }
}
```

## 3. 使用方法

### 3.1 新建一个 AISE 任务

```
/aise 给 data-bank 增加批量导出功能
```

整个流程包括：
1. 文档产出 → 调用 `superpowers:brainstorming` + `ms-requirements`
2. 用户对齐 → `EnterPlanMode`
3. 任务分割 DAG → 调用 `planning-with-files:plan`
4. TDD 执行 → 调用 `superpowers:test-driven-development`
5. 客观验证 → 运行 `aise_verify.py`
6. 多 persona 审查 → 调用 `compound-engineering:ce-review`
7. 熔断判断 → 运行 `aise_fuse.py`
8. 知识沉淀 → 调用 `compound-engineering:ce-compound` + `aise_sediment.py`
9. 健康度报表 → 运行 `aise_dashboard.py`

### 3.2 中途中断后续跑

`/aise` 自动读取 `.aise/progress.md`，询问是否继续。

### 3.3 手动沉淀 pattern

```bash
python ~/.claude/scripts/aise_sediment.py \
  --title "Oracle IN 子句分批处理" \
  --body "每批 500 条，留安全余量..." \
  --tags oracle batch \
  --global
```

### 3.4 查看健康度

```bash
python ~/.claude/scripts/aise_dashboard.py
```

报表输出到 `C:\Users\sundehui\Documents\reports\YYYY-MM-DD-aise-health.md`

## 4. 优化点与组件映射

| 优化点 | 实现方式 |
|--------|---------|
| ① 客观验证门禁 | `aise_verify.py` + `superpowers:verification-before-completion` |
| ② 多 persona 并行审查 | `compound-engineering:ce-review` + `.aise/review-config.md` |
| ③ TDD 前置 | `superpowers:test-driven-development` |
| ④ DAG 任务分割 | `planning-with-files:plan` + `ms-dev-tasks` |
| ⑤ 智能熔断 | `aise_fuse.py`（模式识别 + token + 爆炸半径） |
| ⑥ Clean-room 审查 | `Agent` 工具 `isolation: worktree` + 精简 prompt |
| ⑦ 知识沉淀闭环 | `compound-engineering:ce-compound` + `aise_sediment.py` |
| ⑧ 用户对齐 Checkpoint | Claude Code 原生 `EnterPlanMode` |
| ⑨ 结构化上下文注入 | `aise_inject_context.py` (SessionStart hook) |
| ⑩ 成本质量双轨监控 | `aise_track.py` (PostToolUse) + `aise_dashboard.py` |

## 5. 调参指南

### 熔断阈值（`aise_fuse.py` 参数）

| 参数 | 默认值 | 调高场景 | 调低场景 |
|------|--------|---------|---------|
| `RepeatErrorThreshold` | 2 | 复杂迁移任务 | 严格质量要求 |
| `TokenBudget` | 200000 | 大型重构 | 个人小项目 |
| `FileBlastRadius` | 15 | 跨模块重构 | 仅修单个 bug |

### 验证步骤（`aise_verify.py`）

- 默认按项目类型探测：Maven / Gradle / npm / Python
- 超时：单步默认 300 秒
- 扩展：若有自定义验证脚本，可手动加入 `Run-Step` 调用

## 6. 故障排查

### 6.1 Hook 不触发

1. 确认 `~/.claude/settings.json` 中 hooks 部分语法正确：
   ```
   python -c "import json; json.load(open(r'C:\Users\sundehui\.claude\settings.json'))"
   ```
2. 重启 Claude Code（hooks 在启动时加载）
3. 测试脚本能否直接运行：
   ```
   python ~/.claude/scripts/aise_track.py
   ```

### 6.2 验证脚本误判

- 编辑 `aise_verify.py`，按项目实际命令调整 `Run-Step` 调用
- 可在项目根目录创建 `.aise/verify-override.py`，脚本会优先调用

### 6.3 settings.json 损坏

恢复备份：
```
copy ~/.claude/settings.json.bak-YYYYMMDD-HHMMSS ~/.claude/settings.json
```

## 7. 扩展建议

- **团队推广**：将 `~/.claude/scripts/aise_*.py` 迁移到团队私服或 git 仓库
- **CI 集成**：把 `aise_verify.py` 接入 GitLab CI / GitHub Actions
- **AI 增强 patterns 检索**：把 `aise_inject_context.py` 升级为向量检索（使用 LiteRAG）
- **跨平台 Python 实现**：仅依赖标准库，支持 Windows / Linux / macOS

### 跨平台注意事项

- **Python 版本**：3.8+
- **依赖**：零外部依赖，仅使用标准库（无需 pip install）
- **Windows**：默认使用 `python` 命令
- **Linux / macOS**：若系统命令为 `python3`，需修改 `~/.claude/settings.json` hooks 中的 `python` → `python3`
- **编码**：所有脚本内部强制 UTF-8，跨平台不会乱码
- **路径处理**：使用 `pathlib.Path` 统一处理，自动适配 OS 分隔符

## 8. 设计原则备忘

- **KISS**：每个脚本职责单一，加起来不超过 1000 行
- **复用 > 自建**：能用现成 Skill 就不重写
- **可观测**：所有动作产生 JSONL 日志，便于后续分析
- **可回滚**：所有破坏性操作（hook 注册、settings 修改）有备份
- **证据优先**：硬门禁阻断在主观审查之前

## 9. 相关文档

- v2 流程图：`C:\Users\sundehui\Documents\AISE过程增强审查机制流程图_v2.drawio`
- Compound + Superpowers 最佳实践：`~/.claude/docs/workflow-best-practices.md`
- 全局 patterns 库：`~/.claude/docs/patterns/`
