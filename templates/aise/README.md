# .aise/ 目录说明

本目录由 `/aise` 命令维护，记录单次任务的全流程产物。

## 文件清单

| 文件 | 用途 |
|------|------|
| `progress.md` | 阶段进度追踪 |
| `plan.md` | DAG 任务分割（YAML 格式） |
| `review-config.md` | 多 persona 审查配置 |
| `error_patterns.jsonl` | 错误模式日志（熔断判断依据） |
| `metrics.jsonl` | 监控指标日志（仪表盘数据源） |
| `patterns/` | 本项目沉淀的 patterns（高价值会提升到全局） |

## 生命周期

- 任务开始：`aise_init.py` 创建以上文件
- 任务进行：各脚本追加日志
- 任务结束：`aise_sediment.py` 沉淀 patterns；progress.md 归档到 `docs/req/`
- 下次任务：error_patterns.jsonl / metrics.jsonl 滚动追加（不清空）

## 是否加入版本控制

- `progress.md` `plan.md` `review-config.md` `patterns/` → 建议提交
- `error_patterns.jsonl` `metrics.jsonl` → 建议加入 `.gitignore`（仅本地参考）
