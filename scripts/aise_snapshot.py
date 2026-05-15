#!/usr/bin/env python3
"""AISE plan snapshot 工具（方案 A 子项 2）

子命令：
  create  — 基于 .aise/plan.md 当前内容生成 plan.snapshot.json + plan.snapshot.sha256
  check   — 校验 snapshot 未被篡改（gate 启动可调）
  show    — 打印 snapshot 内容摘要

退出码：
  0 = ok
  1 = 业务失败（参数错误 / plan.md 不存在）
  2 = snapshot 未通过（不存在 / 被篡改 / sha 不一致）
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import snapshot as snap_lib  # noqa: E402


def cmd_create(project_root: Path, task_title: str) -> int:
    try:
        snap_path, sha = snap_lib.create_snapshot(project_root, task_title=task_title)
    except FileNotFoundError as e:
        print(f"[AISE-snapshot] {e}", file=sys.stderr)
        return 1
    print(f"[AISE-snapshot] created: {snap_path}")
    print(f"                sha256: {sha}")
    return 0


def cmd_check(project_root: Path) -> int:
    ok, code, snap = snap_lib.check_snapshot(project_root)
    if ok:
        print(f"[AISE-snapshot] OK — captured_at={snap.get('captured_at')}")
        return 0
    print(f"[AISE-snapshot] FAIL: code={code}", file=sys.stderr)
    if code == "snapshot_missing":
        print("  请先走 /aise 的步骤 2 → ExitPlanMode 后生成 snapshot", file=sys.stderr)
    elif code == "snapshot_tampered":
        print("  plan.snapshot.json 被改过，与 plan.snapshot.sha256 不一致", file=sys.stderr)
        print("  排查：git diff .aise/plan.snapshot.json 或重新生成 snapshot", file=sys.stderr)
    return 2


def cmd_show(project_root: Path) -> int:
    ok, code, snap = snap_lib.check_snapshot(project_root)
    if not ok:
        print(f"[AISE-snapshot] FAIL: code={code}", file=sys.stderr)
        return 2
    print(json.dumps(
        {k: (v if k != "plan_md_body" else f"<{len(v)} chars>") for k, v in snap.items()},
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE plan snapshot 工具")
    parser.add_argument("subcommand", choices=["create", "check", "show"])
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--task-title", default="")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()

    if args.subcommand == "create":
        return cmd_create(project_root, args.task_title)
    if args.subcommand == "check":
        return cmd_check(project_root)
    if args.subcommand == "show":
        return cmd_show(project_root)
    return 1


if __name__ == "__main__":
    sys.exit(main())
