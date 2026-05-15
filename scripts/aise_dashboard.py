#!/usr/bin/env python3
"""AISE 健康度仪表盘（优化⑩）- 跨平台 Python 版

读取 .aise/metrics.jsonl 与 .aise/error_patterns.jsonl，生成 markdown 报表。
v1.1 新增：启动时校验 plan.snapshot.json 防篡改（如已存在）。
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import snapshot as snap_lib  # noqa: E402


def load_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--skip-snapshot-check", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path.home() / "Documents" / "reports"
    )

    aise_dir = project_root / ".aise"

    # gate 启动门禁
    if not args.skip_snapshot_check and (aise_dir / "plan.snapshot.json").exists():
        snap_lib.require_snapshot(project_root, gate_name="dashboard")

    metrics_path = aise_dir / "metrics.jsonl"
    error_path = aise_dir / "error_patterns.jsonl"

    if not metrics_path.exists():
        print("[AISE-dashboard] 无 metrics 数据")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = load_jsonl(metrics_path)
    errors = load_jsonl(error_path)

    # 阶段统计
    phase_counter = Counter(m.get("phase") for m in metrics)

    # 验证通过率
    verify_entries = [m for m in metrics if m.get("phase") == "verify"]
    verify_pass = sum(1 for v in verify_entries if v.get("pass"))
    verify_total = len(verify_entries)
    verify_rate = round(verify_pass / verify_total * 100, 1) if verify_total else 0.0

    # 熔断次数
    fuse_count = sum(1 for m in metrics if m.get("phase") == "fuse" and m.get("triggered"))

    # 错误分布
    error_dist = Counter(e["error_type"] for e in errors if e.get("is_error") and e.get("error_type"))

    # token / 文件
    total_tokens = sum(e.get("est_tokens", 0) for e in errors)
    unique_files = len({e["file"] for e in errors if e.get("file")})

    # 健康度评分
    if total_tokens < 50000:
        cost_score = 30
    elif total_tokens < 150000:
        cost_score = 20
    else:
        cost_score = 10
    quality_score = round(verify_rate * 0.4)
    pattern_dir = aise_dir / "patterns"
    pattern_count = len(list(pattern_dir.glob("*.md"))) if pattern_dir.exists() else 0
    closure_score = min(30, pattern_count * 5)
    health = cost_score + quality_score + closure_score

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = output_dir / f"{today}-aise-health.md"

    phase_lines = "\n".join(f"- {k}: {v} 次" for k, v in phase_counter.items()) or "（无）"
    error_lines = (
        "\n".join(f"- {k}: {v} 次" for k, v in error_dist.most_common(5))
        or "（无）"
    )

    tips = []
    if verify_rate < 70:
        tips.append("- 验证通过率偏低，建议补充测试或加强 TDD 习惯")
    if fuse_count > 0:
        tips.append(f"- 触发过熔断 {fuse_count} 次，建议复盘错误模式")
    if total_tokens > 150000:
        tips.append("- Token 消耗较高，建议拆分更细粒度任务")
    if closure_score < 10:
        tips.append("- 沉淀 patterns 不足，建议任务结束后运行 aise_sediment.py")
    if not tips:
        tips = ["- 各项指标良好，继续保持"]

    report = f"""# AISE 健康度报表

- 项目：{project_root.name} ({project_root})
- 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- 数据来源：`{metrics_path}`

## 综合健康度：{health} / 100

| 维度 | 得分 | 说明 |
|------|------|------|
| 成本指数 | {cost_score} / 30 | 累计 token: {total_tokens} |
| 质量指数 | {quality_score} / 40 | 验证通过率: {verify_rate}% |
| 闭环指数 | {closure_score} / 30 | 沉淀 patterns 数: {pattern_count} |

## 阶段执行统计

{phase_lines}

## 客观验证

- 总次数：{verify_total}
- 通过次数：{verify_pass}
- 通过率：{verify_rate}%

## 熔断告警

- 触发次数：{fuse_count}

## 错误类型 Top 5

{error_lines}

## 工具调用足迹

- 总条目：{len(errors)}
- 涉及文件数：{unique_files}
- 累计 token 估算：{total_tokens}

## 改进建议

{chr(10).join(tips)}
"""

    report_path.write_text(report, encoding="utf-8")
    print(f"[AISE-dashboard] 报表已生成: {report_path}")
    print(f"[AISE-dashboard] 健康度: {health} / 100")
    return 0


if __name__ == "__main__":
    sys.exit(main())
