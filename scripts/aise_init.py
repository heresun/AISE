#!/usr/bin/env python3
"""AISE 项目初始化 - 跨平台 Python 版

用途：在当前项目根目录创建 .aise/ 工作区并复制模板。
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "aise"


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 项目初始化")
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--task-title", default="", help="任务标题")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    aise_dir = project_root / ".aise"
    patterns_dir = aise_dir / "patterns"

    if not TEMPLATE_DIR.exists():
        print(f"模板目录不存在: {TEMPLATE_DIR}", file=sys.stderr)
        return 1

    aise_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)

    for item in TEMPLATE_DIR.iterdir():
        dst = aise_dir / item.name
        if dst.exists():
            continue
        if item.is_file():
            shutil.copy2(item, dst)
        elif item.is_dir():
            shutil.copytree(item, dst)

    for log in ("error_patterns.jsonl", "metrics.jsonl"):
        fp = aise_dir / log
        if not fp.exists():
            fp.touch()

    progress_path = aise_dir / "progress.md"
    if progress_path.exists():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = progress_path.read_text(encoding="utf-8")
        content = content.replace("启动时间：（待填充）", f"启动时间：{now}")
        content = content.replace("项目路径：（待填充）", f"项目路径：{project_root}")
        if args.task_title:
            content = content.replace("任务标题：（待填充）", f"任务标题:{args.task_title}")
        progress_path.write_text(content, encoding="utf-8")

    print(f"[AISE] 初始化完成: {aise_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
