# AISE plan.json Schema (v1.0)

> v3.3 架构补完。AISE 主流程 ExitPlanMode 后由 `aise_run_init.py` 解析 +
> 校验 `.aise/plan.json`，分配 run_id，创建 `.aise/runs/<run_id>/run_context.json`
> 供下游所有 gate 使用。

---

## 1. 文件位置

- `.aise/plan.md` — 人类可读描述（自由 markdown，保留作为 task 上下文）
- `.aise/plan.json` — **机器可读结构（aise_run_init 必须的输入）**

---

## 2. Schema (v1.0)

```jsonc
{
  "schema_version": "1.0",                // 必填，目前固定 "1.0"
  "task_title": "实现 Calc 服务",          // 必填，顶级任务标题
  "created_at": "2026-05-17T12:00:00Z",   // 可选，ISO 8601
  "tasks": [                              // 必填，非空 list
    {
      "task_id": "T-001",                 // 必填，唯一字符串（推荐 T-NNN）
      "title": "Calc.add 实现 + 单测",    // 必填
      "scope": {
        "paths": [                        // 必填，非空。glob 风格，相对项目根
          "src/calc/**",
          "tests/test_calc*.py"
        ]
      },
      "acceptance": "calc.add(2,3) == 5", // 可选，验收标准简述
      "test_manifest": {
        "pipe": "pytest-junitxml",        // 必填，5 选 1（PIPE_DEFS 内）
        "targets": ["tests/test_calc.py"] // 可选，runner 接收的 target 列表
      },
      "dependencies": [],                 // 可选 task_id 列表，按拓扑序执行
      "shared_evidence_tasks": []         // 可选 task_id 列表，互相背书证据
    }
  ]
}
```

---

## 3. 校验规则（aise_run_init）

### 3.1 顶级
| 字段 | 必填 | 校验 |
|---|:---:|---|
| `schema_version` | ✅ | 必须 `"1.0"` |
| `task_title` | ✅ | 非空字符串 |
| `tasks` | ✅ | 非空 list |
| `created_at` | ⛔ | 可缺；存在时必须 ISO 8601 |

### 3.2 每个 task
| 字段 | 必填 | 校验 |
|---|:---:|---|
| `task_id` | ✅ | 非空字符串；全局唯一 |
| `title` | ✅ | 非空字符串 |
| `scope.paths` | ✅ | 非空 list，每项非空字符串 |
| `test_manifest.pipe` | ✅ | 必须在 `PIPE_DEFS` 5 种之一 |
| `test_manifest.targets` | ⛔ | 可缺，runner 用 default |
| `acceptance` | ⛔ | 可缺；建议人类可读 |
| `dependencies` | ⛔ | task_id 列表，每个 id 必须存在 |
| `shared_evidence_tasks` | ⛔ | task_id 列表；不能与本 task scope 完全 disjoint |

### 3.3 全局
- `task_id` 全局唯一
- `dependencies` 不能有环
- `shared_evidence_tasks` scope 与本 task scope 至少有 1 个 glob 交集（v3.2.5 P1-C）
  - 例外：`allow_disjoint_shared_evidence: true` 顶级标志 → 降级为 warn

校验失败 → `aise_run_init.py` exit 2 + 列出违规项。

---

## 4. 输出：run_context.json

`aise_run_init.py` 成功后产出 `.aise/runs/<run_id>/run_context.json`：

```jsonc
{
  "run_id": "20260517-120000-abc123",     // ISO 时间戳 + 6 字符随机
  "schema_version": "1.0",
  "started_at": "2026-05-17T12:00:00.123Z",
  "project_root": "/abs/path/to/project",
  "plan_snapshot": {
    "path": ".aise/plan.snapshot.json",
    "sha256": "...64 char hex..."
  },
  "git": {
    "head": "abc123...",                  // git rev-parse HEAD
    "branch": "main"
  },
  "scope_policy": {
    "mtime_window_tolerance_ms": 2000     // 默认值，可被 plan 顶级 override
  },
  "tasks": [...]                          // 校验后的 tasks（含 normalized scope）
}
```

下游 gate（scope_check / freshness / TDD / verify）启动时：
1. 读 `.aise/runs/<latest>/run_context.json`（in-memory 缓存，process-local）
2. 校验 `plan_snapshot.sha256` 与盘上一致
3. 任何不一致 → exit 2 `run_context_tampered`

---

## 5. 模板与例子

见 `templates/aise/plan.json`（最小可工作模板）。
