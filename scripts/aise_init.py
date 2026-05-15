#!/usr/bin/env python3
"""AISE 项目初始化 — 跨平台 Python 版

用途：在当前项目根目录创建 .aise/ 工作区并复制模板。

v1.1 新增（方案 A）：用户 ExitPlanMode 后由 /aise 主流程调用 `--snapshot` 子命令
（或单独执行 aise_snapshot.py create）生成 plan.snapshot.json + plan.snapshot.sha256，
关闭"中途篡改 plan"窗口。
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# scripts/lib 可 import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import snapshot as snap_lib  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "aise"


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 项目初始化")
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--task-title", default="", help="任务标题")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="（用户对齐 plan 后调用）基于当前 plan.md 生成 plan.snapshot.json + .sha256",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    aise_dir = project_root / ".aise"
    patterns_dir = aise_dir / "patterns"
    runs_dir = aise_dir / "runs"

    if args.snapshot:
        # 仅生成 snapshot，不再做模板拷贝
        try:
            snap_path, snap_sha = snap_lib.create_snapshot(project_root, task_title=args.task_title)
        except FileNotFoundError as e:
            print(f"[AISE] snapshot 失败: {e}", file=sys.stderr)
            print("[AISE] 请先确保 .aise/plan.md 存在并已写入计划", file=sys.stderr)
            return 1
        print(f"[AISE] plan snapshot 已生成: {snap_path}")
        print(f"       sha256={snap_sha}")
        return 0

    if not TEMPLATE_DIR.exists():
        print(f"模板目录不存在: {TEMPLATE_DIR}", file=sys.stderr)
        return 1

    aise_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

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
    print(f"[AISE] 提示：plan.md 由用户/编排器填好后，运行 'python aise_init.py --snapshot' 锁定计划")
    return 0


if __name__ == "__main__":
    sys.exit(main())
