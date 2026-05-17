#!/usr/bin/env python3
"""AISE scope gate — worker 提交前强校验（v3.3 架构 T3）

确保 worker 改的文件都落在 declared task.scope.paths 之内。越界 → exit 1。
配合 aise_run_init.py 产出的 run_context.json 一起工作。

流程：
  1. 找最新 .aise/runs/<run_id>/run_context.json（或 --run-id 指定）
  2. plan.snapshot.json 防篡改校验
  3. 提取 task.scope.paths
  4. git status --porcelain 列变更文件
  5. 每个文件用 fnmatch + 路径分隔符归一检查
  6. 违规 → exit 1 + 列出文件 + scope

退出码：
  0 = scope 内
  1 = 越界（gate 触发）
  2 = 状态异常（run_context 缺 / snapshot 篡改 / task_id 未知 / git 不可用）
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import snapshot as snap_lib  # noqa: E402


def _err(msg: str) -> None:
    print(f"[AISE-scope-check] {msg}", file=sys.stderr)


def _normalize_path(p: str) -> str:
    return p.replace("\\", "/")


def _matches_scope(file_path: str, patterns: List[str]) -> bool:
    """复用 event_runner 的归一+glob 思路。"""
    norm = _normalize_path(file_path)
    for pat in patterns:
        npat = _normalize_path(pat)
        if fnmatch.fnmatchcase(norm, npat):
            return True
        if "**" in npat:
            relaxed = npat.replace("**", "*")
            if fnmatch.fnmatchcase(norm, relaxed):
                return True
    return False


def _find_latest_run_dir(project_root: Path) -> Path | None:
    runs_root = project_root / ".aise" / "runs"
    if not runs_root.exists():
        return None
    candidates = sorted(
        [d for d in runs_root.iterdir() if d.is_dir() and (d / "run_context.json").exists()],
        reverse=True,
    )
    return candidates[0] if candidates else None


def _run_git(project_root: Path, *args: str) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def _git_changed_files(project_root: Path) -> Tuple[List[str], str | None]:
    """返回 (changed_files, error_msg)。

    用 git diff + git ls-files 组合，避免 git status 折叠 untracked 目录：
      1. `git diff --name-only -z HEAD`         tracked 文件 M/A/D/R/C
      2. `git ls-files --others --exclude-standard -z`  untracked 文件（展开）
    rename 通过 diff --name-only 自动处理（only 模式输出 newpath；
    若想含 oldpath 可改 --name-status 解析）。
    """
    files: List[str] = []

    # tracked 变更
    rc, out, err = _run_git(project_root, "diff", "--name-only", "-z", "HEAD")
    if rc != 0:
        return [], f"git diff 失败 ({rc}): {err.strip()}"
    files.extend([p for p in out.split("\0") if p])

    # untracked
    rc, out, err = _run_git(
        project_root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if rc != 0:
        return [], f"git ls-files 失败 ({rc}): {err.strip()}"
    files.extend([p for p in out.split("\0") if p])

    # 去重保序
    seen: set = set()
    uniq: List[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq, None


def _find_task(tasks: List[Dict[str, Any]], task_id: str) -> Dict[str, Any] | None:
    for t in tasks:
        if t.get("task_id") == task_id:
            return t
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE scope gate")
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--run-id", default=None, help="run id（默认最新）")
    parser.add_argument("--task-id", required=True, help="当前正在执行的 task_id")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()

    # 1. 定位 run_context
    if args.run_id:
        run_dir = project_root / ".aise" / "runs" / args.run_id
        if not run_dir.exists() or not (run_dir / "run_context.json").exists():
            _err(f"指定的 run_id {args.run_id!r} 未找到 run_context.json")
            return 2
    else:
        latest = _find_latest_run_dir(project_root)
        if latest is None:
            _err("未找到 .aise/runs/*/run_context.json — 请先跑 aise_run_init.py")
            return 2
        run_dir = latest

    ctx_path = run_dir / "run_context.json"
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _err(f"读 run_context 失败: {e}")
        return 2

    # 2. snapshot 防篡改（复用 lib.snapshot 的 require_snapshot 但不退出，自己处理）
    ok, code, _snap = snap_lib.check_snapshot(project_root)
    if not ok:
        _err(f"plan snapshot 校验失败 (code={code})")
        _err(f"  恢复：重新走 ExitPlanMode → aise_run_init.py")
        return 2

    # 3. 找 task
    tasks = ctx.get("tasks", [])
    task = _find_task(tasks, args.task_id)
    if task is None:
        _err(f"task_id {args.task_id!r} 不在 run_context 中（已知: "
             f"{[t.get('task_id') for t in tasks]}）")
        return 2

    scope_paths = task.get("scope", {}).get("paths", [])
    if not scope_paths:
        _err(f"task {args.task_id} 的 scope.paths 为空（理论不会发生，run_init 应已拦截）")
        return 2

    # 4. git diff
    changed, err_msg = _git_changed_files(project_root)
    if err_msg:
        _err(err_msg)
        return 2

    # .aise/ 目录下文件视为"AISE 自身产物"，不参与 scope 校验
    changed = [
        f for f in changed
        if not (_normalize_path(f).startswith(".aise/") or _normalize_path(f) == ".aise")
    ]

    if not changed:
        print(f"[AISE-scope-check] OK  task={args.task_id}  无文件变更")
        return 0

    # 5. 检查每个文件
    violations: List[str] = []
    for f in changed:
        if not _matches_scope(f, scope_paths):
            violations.append(f)

    if violations:
        print(f"[AISE-scope-check] FAIL  task={args.task_id}")
        print(f"  scope.paths: {scope_paths}")
        print(f"  越界文件 ({len(violations)} 个):")
        for v in violations:
            print(f"    - {v}")
        return 1

    print(f"[AISE-scope-check] OK  task={args.task_id}  "
          f"{len(changed)} 个变更文件全部在 scope 内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
