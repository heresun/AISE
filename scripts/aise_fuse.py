#!/usr/bin/env python3
"""AISE 智能熔断判断（优化⑤）- 跨平台 Python 版

退出码：0 = 未触发；2 = 触发熔断
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 智能熔断")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--repeat-threshold", type=int, default=2, help="同类错误重复阈值")
    parser.add_argument("--token-budget", type=int, default=200000, help="累计 token 上限")
    parser.add_argument("--blast-radius", type=int, default=15, help="文件改动数上限")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    aise_dir = project_root / ".aise"
    log_path = aise_dir / "error_patterns.jsonl"

    if not log_path.exists():
        print("[AISE-fuse] 无错误日志，未触发熔断")
        return 0

    lines = log_path.read_text(encoding="utf-8").splitlines()[-100:]
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        print("[AISE-fuse] 无有效日志")
        return 0

    triggers = []

    # 1. 同类错误重复
    error_types = [e["error_type"] for e in entries if e.get("is_error") and e.get("error_type")]
    for err_type, count in Counter(error_types).items():
        if count >= args.repeat_threshold:
            triggers.append(f"同类错误 [{err_type}] 重复出现 {count} 次")

    # 2. token 超限
    total_tokens = sum(e.get("est_tokens", 0) for e in entries)
    if total_tokens > args.token_budget:
        triggers.append(f"累计 token 估算 {total_tokens} 超过预算 {args.token_budget}")

    # 3. 爆炸半径
    unique_files = len({e["file"] for e in entries if e.get("file")})
    if unique_files > args.blast_radius:
        triggers.append(f"改动文件数 {unique_files} 超过爆炸半径阈值 {args.blast_radius}")

    # 4. 修 A 引 B
    recent_errors = [e for e in entries[-10:] if e.get("is_error")]
    switch_count = 0
    last_type = None
    for e in recent_errors:
        if last_type is not None and e.get("error_type") != last_type:
            switch_count += 1
        last_type = e.get("error_type")
    if switch_count >= 2:
        triggers.append(f"错误类型频繁切换 ({switch_count} 次)，疑似修 A 引 B")

    if not triggers:
        print("[AISE-fuse] 未触发熔断，可以继续修复")
        return 0

    print("[AISE-fuse] 熔断触发：")
    for t in triggers:
        print(f"  - {t}")

    metrics_path = aise_dir / "metrics.jsonl"
    entry = {
        "ts": datetime.now().isoformat(),
        "phase": "fuse",
        "triggered": True,
        "reasons": triggers,
    }
    with metrics_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return 2


if __name__ == "__main__":
    sys.exit(main())
