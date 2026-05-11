#!/usr/bin/env python3
"""AISE 知识沉淀（优化⑦）- 跨平台 Python 版

把本次踩坑/优解写入 .aise/patterns/，可选同步到全局 ~/.claude/docs/patterns/。
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def safe_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", title)
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE patterns 沉淀")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True, help="可以是 markdown 内容或 @file_path")
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument("--global", dest="is_global", action="store_true", help="同时写入全局库")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    project_patterns = project_root / ".aise" / "patterns"
    global_patterns = Path.home() / ".claude" / "docs" / "patterns"

    project_patterns.mkdir(parents=True, exist_ok=True)
    if args.is_global:
        global_patterns.mkdir(parents=True, exist_ok=True)

    # 支持 @file_path 读取内容
    body = args.body
    if body.startswith("@"):
        body_path = Path(body[1:])
        if body_path.exists():
            body = body_path.read_text(encoding="utf-8")

    timestamp = datetime.now().strftime("%Y-%m-%d")
    file_name = f"{timestamp}-{safe_filename(args.title)}.md"

    tags_str = ", ".join(f'"{t}"' for t in args.tags)
    content = (
        "---\n"
        f"title: {args.title}\n"
        f"date: {timestamp}\n"
        f"tags: [{tags_str}]\n"
        "source: AISE 沉淀\n"
        "---\n\n"
        f"# {args.title}\n\n"
        f"{body}\n"
    )

    project_path = project_patterns / file_name
    project_path.write_text(content, encoding="utf-8")
    print(f"[AISE-sediment] 项目级 pattern 已写入: {project_path}")

    if args.is_global:
        global_path = global_patterns / file_name
        global_path.write_text(content, encoding="utf-8")
        print(f"[AISE-sediment] 全局 pattern 已写入: {global_path}")

    aise_dir = project_root / ".aise"
    if aise_dir.exists():
        metrics_path = aise_dir / "metrics.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "phase": "sediment",
            "title": args.title,
            "is_global": bool(args.is_global),
            "tags": args.tags,
        }
        with metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
