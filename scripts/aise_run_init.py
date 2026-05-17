#!/usr/bin/env python3
"""AISE run 初始化 — v3.3 架构入口

ExitPlanMode 后由 /aise 主流程调用。流程：
  1. 解析 .aise/plan.json
  2. schema 校验（docs/plan-schema.md）
  3. 分配 run_id = YYYYMMDD-HHMMSS-<6 hex>
  4. 创建 .aise/runs/<run_id>/
  5. plan.snapshot.json 生成并绑定
  6. 写 .aise/runs/<run_id>/run_context.json

退出码：
  0 = 通过 + run_context 已落盘
  1 = 业务异常（应该极少发生）
  2 = plan 不存在 / 校验失败 / snapshot 失败
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import event_runner as er  # noqa: E402
from lib import snapshot as snap_lib  # noqa: E402


DEFAULT_MTIME_TOLERANCE_MS = 2000


def _err(msg: str) -> None:
    print(f"[AISE-run-init] {msg}", file=sys.stderr)


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _generate_run_id() -> str:
    now = datetime.now()
    return now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


# -------------------- plan 校验 --------------------


def _validate_top_level(plan: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if plan.get("schema_version") != "1.0":
        errors.append(f"schema_version 必须为 '1.0'，got {plan.get('schema_version')!r}")
    if not isinstance(plan.get("task_title"), str) or not plan["task_title"].strip():
        errors.append("task_title 必须为非空字符串")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0:
        errors.append("tasks 必须为非空 list")
    return errors


def _validate_one_task(task: Any, index: int) -> List[str]:
    errs: List[str] = []
    prefix = f"tasks[{index}]"
    if not isinstance(task, dict):
        return [f"{prefix} 必须为对象"]

    if not isinstance(task.get("task_id"), str) or not task["task_id"].strip():
        errs.append(f"{prefix}.task_id 必填非空字符串")
    if not isinstance(task.get("title"), str) or not task["title"].strip():
        errs.append(f"{prefix}.title 必填非空字符串")

    scope = task.get("scope")
    if not isinstance(scope, dict):
        errs.append(f"{prefix}.scope 必须为对象")
    else:
        paths = scope.get("paths")
        if not isinstance(paths, list) or len(paths) == 0:
            errs.append(f"{prefix}.scope.paths 必须为非空 list")
        elif any((not isinstance(p, str)) or (not p.strip()) for p in paths):
            errs.append(f"{prefix}.scope.paths 每项必须为非空字符串")

    tm = task.get("test_manifest")
    if not isinstance(tm, dict):
        errs.append(f"{prefix}.test_manifest 必须为对象")
    else:
        pipe = tm.get("pipe")
        if pipe not in er.PIPE_DEFS:
            errs.append(
                f"{prefix}.test_manifest.pipe={pipe!r} 不在 PIPE_DEFS"
                f" ({sorted(er.PIPE_DEFS.keys())})"
            )

    deps = task.get("dependencies", [])
    if not isinstance(deps, list):
        errs.append(f"{prefix}.dependencies 必须为 list")

    shared = task.get("shared_evidence_tasks", [])
    if not isinstance(shared, list):
        errs.append(f"{prefix}.shared_evidence_tasks 必须为 list")

    return errs


def _check_duplicate_task_ids(tasks: List[Dict[str, Any]]) -> List[str]:
    seen: Dict[str, int] = {}
    errors: List[str] = []
    for i, t in enumerate(tasks):
        tid = t.get("task_id")
        if isinstance(tid, str) and tid in seen:
            errors.append(f"duplicate task_id {tid!r} at tasks[{i}] (first at tasks[{seen[tid]}])")
        elif isinstance(tid, str):
            seen[tid] = i
    return errors


def _check_dependencies(tasks: List[Dict[str, Any]]) -> List[str]:
    """校验：1) dep 引用存在；2) 拓扑无环（DFS）."""
    errors: List[str] = []
    ids = {t.get("task_id") for t in tasks if isinstance(t.get("task_id"), str)}
    graph: Dict[str, List[str]] = {}
    for t in tasks:
        tid = t.get("task_id")
        if not isinstance(tid, str):
            continue
        deps = t.get("dependencies", [])
        if not isinstance(deps, list):
            continue
        for d in deps:
            if d not in ids:
                errors.append(f"task {tid!r}.dependencies 引用不存在的 task_id {d!r}")
        graph[tid] = [d for d in deps if d in ids]

    # DFS 检环
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {tid: WHITE for tid in graph}

    def dfs(node: str, path: List[str]) -> bool:
        color[node] = GRAY
        for nb in graph.get(node, []):
            if color.get(nb, WHITE) == GRAY:
                errors.append(
                    f"dependency cycle detected: {' -> '.join(path + [nb])}"
                )
                return True
            if color.get(nb, WHITE) == WHITE and dfs(nb, path + [nb]):
                return True
        color[node] = BLACK
        return False

    for tid in list(graph.keys()):
        if color[tid] == WHITE:
            if dfs(tid, [tid]):
                break  # 一个环够说明问题

    return errors


def _static_prefix(path: str) -> str:
    """取 glob 中第一个通配符前的"静态前缀"。

    例：
      "src/auth/**"          → "src/auth"
      "tests/test_*.py"      → "tests"
      "**"                   → ""（空前缀 = 整根）
      "src/*/foo"            → "src"
    """
    norm = path.replace("\\", "/").lstrip("./")
    parts: List[str] = []
    for seg in norm.split("/"):
        if "*" in seg or "?" in seg or "[" in seg:
            break
        if seg:
            parts.append(seg)
    return "/".join(parts)


def _scopes_intersect(paths_a: List[str], paths_b: List[str]) -> bool:
    """两组 glob 是否可能相交（v3.2.5 §10.4 scopesMayOverlap 简化版）。

    策略：把每条 glob 归一为静态前缀，任一对 (a, b) 存在 prefix 包含
    关系 → 相交。"src/auth/**" 与 "src/billing/**" 静态前缀分别是
    "src/auth"、"src/billing"，互不包含 → disjoint（正确）。

    空前缀（如 "**"）视为根 → 与一切相交。
    """
    sps_a = [_static_prefix(p) for p in paths_a]
    sps_b = [_static_prefix(p) for p in paths_b]
    if any(sp == "" for sp in sps_a) or any(sp == "" for sp in sps_b):
        return True
    for sa in sps_a:
        for sb in sps_b:
            # 同一段内 prefix 包含；用 "/" 边界避免 src/au 误命中 src/auth
            sa_b = sa + "/"
            sb_b = sb + "/"
            if sa == sb or sa_b.startswith(sb_b) or sb_b.startswith(sa_b):
                return True
    return False


def _check_shared_evidence_scopes(plan: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    allow_disjoint = bool(plan.get("allow_disjoint_shared_evidence", False))
    tasks_by_id = {
        t["task_id"]: t for t in plan.get("tasks", []) if isinstance(t.get("task_id"), str)
    }
    for t in plan.get("tasks", []):
        tid = t.get("task_id")
        if not isinstance(tid, str):
            continue
        shared = t.get("shared_evidence_tasks", [])
        if not isinstance(shared, list):
            continue
        own_paths = t.get("scope", {}).get("paths", [])
        for other_id in shared:
            other = tasks_by_id.get(other_id)
            if other is None:
                continue  # 单独由 _check_dependencies/类似流程报，这里跳过
            other_paths = other.get("scope", {}).get("paths", [])
            if not _scopes_intersect(own_paths, other_paths):
                msg = (
                    f"task {tid!r}.shared_evidence_tasks → {other_id!r} "
                    f"scope disjoint (own={own_paths}, other={other_paths})"
                )
                if allow_disjoint:
                    print(f"[AISE-run-init] WARN: {msg}", file=sys.stderr)
                else:
                    errors.append(msg)
    return errors


def validate_plan(plan: Any) -> List[str]:
    """完整校验。返回 errors list（空 list 表示通过）."""
    if not isinstance(plan, dict):
        return ["plan 根必须为对象"]
    errors = _validate_top_level(plan)
    tasks = plan.get("tasks")
    if isinstance(tasks, list):
        for i, t in enumerate(tasks):
            errors.extend(_validate_one_task(t, i))
        errors.extend(_check_duplicate_task_ids(tasks))
        # 仅在 task 个体合法时再做关系级校验，避免噪声
        if not errors:
            errors.extend(_check_dependencies(tasks))
            errors.extend(_check_shared_evidence_scopes(plan))
    return errors


# -------------------- git 探测 --------------------


def _git_info(project_root: Path) -> Dict[str, str]:
    info: Dict[str, str] = {}
    for label, args in [("head", ["rev-parse", "HEAD"]),
                        ("branch", ["rev-parse", "--abbrev-ref", "HEAD"])]:
        try:
            r = subprocess.run(
                ["git", *args],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            info[label] = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            info[label] = ""
    return info


# -------------------- main --------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE run 初始化（plan 校验 + run_id 分配）")
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--task-title-override", default=None,
                        help="覆盖 plan.json 的 task_title（不修改文件，仅 run_context）")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    aise_dir = project_root / ".aise"
    plan_json_path = aise_dir / "plan.json"

    if not plan_json_path.exists():
        _err(f"plan.json 不存在: {plan_json_path}")
        _err("请按 docs/plan-schema.md 创建 .aise/plan.json")
        return 2

    try:
        plan_text = plan_json_path.read_text(encoding="utf-8")
    except OSError as e:
        _err(f"读 plan.json 失败: {e}")
        return 2

    try:
        plan = json.loads(plan_text)
    except json.JSONDecodeError as e:
        _err(f"plan.json 非合法 JSON: {e}")
        return 2

    errors = validate_plan(plan)
    if errors:
        _err(f"plan 校验失败 ({len(errors)} 项)：")
        for e in errors:
            _err(f"  - {e}")
        return 2

    # 校验通过 → 创建 snapshot + run_id
    try:
        snap_path, snap_sha = snap_lib.create_snapshot(
            project_root, task_title=args.task_title_override or plan.get("task_title", "")
        )
    except FileNotFoundError as e:
        _err(f"snapshot 创建失败: {e}")
        return 2

    run_id = _generate_run_id()
    run_dir = aise_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    git = _git_info(project_root)

    run_context = {
        "schema_version": "1.0",
        "run_id": run_id,
        "started_at": _now_iso(),
        "project_root": str(project_root),
        "task_title": args.task_title_override or plan.get("task_title", ""),
        "plan_snapshot": {
            "path": str(snap_path.relative_to(project_root)),
            "sha256": snap_sha,
        },
        "git": git,
        "scope_policy": {
            "mtime_window_tolerance_ms": int(
                plan.get("scope_policy", {}).get(
                    "mtime_window_tolerance_ms", DEFAULT_MTIME_TOLERANCE_MS
                )
            ),
        },
        "tasks": plan["tasks"],
    }

    ctx_path = run_dir / "run_context.json"
    ctx_path.write_text(
        json.dumps(run_context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[AISE-run-init] OK")
    print(f"  run_id:     {run_id}")
    print(f"  run_dir:    {run_dir}")
    print(f"  snapshot:   {snap_path}  (sha256={snap_sha[:12]}…)")
    print(f"  tasks:      {len(plan['tasks'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
