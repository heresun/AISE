"""plan.snapshot.json 防篡改校验

aise_init 在用户 ExitPlanMode 后调用 create_snapshot()，把 plan.md（或 plan.json）的
当前内容快照到 plan.snapshot.json 并记录 sha256 到 plan.snapshot.sha256。

下游 gate（verify/fuse/dashboard）启动时第一件事就是 check_snapshot()：
sha256 不匹配 → exit 2 snapshot_tampered，关闭"中途篡改 plan"的窗口。

注意：snapshot 只校验一次然后缓存到进程内（process-local），防止 gate 长跑中途盘上文件
被换。这是 v3.2.5 P1-D 的核心保护。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


_SNAPSHOT_CACHE: dict[str, Any] | None = None
_SNAPSHOT_CACHE_KEY: str | None = None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot_paths(aise_dir: Path) -> tuple[Path, Path]:
    return aise_dir / "plan.snapshot.json", aise_dir / "plan.snapshot.sha256"


def create_snapshot(project_root: Path, task_title: str = "") -> tuple[Path, str]:
    """从 .aise/plan.md 当前内容生成 snapshot。返回 (snapshot_path, sha256)。

    用户每次 ExitPlanMode 后由 /aise 编排器主动调用一次，覆盖旧 snapshot。
    """
    aise_dir = project_root / ".aise"
    plan_md = aise_dir / "plan.md"
    if not plan_md.exists():
        raise FileNotFoundError(f"plan.md 不存在: {plan_md}")

    plan_content = plan_md.read_text(encoding="utf-8")
    snapshot = {
        "version": 1,
        "task_title": task_title,
        "captured_at": datetime.now().isoformat(),
        "plan_md_path": "plan.md",
        "plan_md_sha256": _sha256_text(plan_content),
        "plan_md_body": plan_content,
    }
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
    snapshot_sha = _sha256_text(snapshot_text)

    snap_path, sha_path = _snapshot_paths(aise_dir)
    snap_path.write_text(snapshot_text, encoding="utf-8")
    sha_path.write_text(snapshot_sha, encoding="utf-8")
    return snap_path, snapshot_sha


def check_snapshot(project_root: Path) -> tuple[bool, str, dict[str, Any] | None]:
    """gate 启动时调用一次。
    返回 (ok, code, snapshot_dict)
       code ∈ {"ok", "snapshot_missing", "sha_missing", "snapshot_tampered"}

    成功后 snapshot 会缓存到进程内存，后续同进程再调用直接返回缓存。
    """
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_KEY
    cache_key = str(project_root.resolve())
    if _SNAPSHOT_CACHE_KEY == cache_key and _SNAPSHOT_CACHE is not None:
        return True, "ok", _SNAPSHOT_CACHE

    aise_dir = project_root / ".aise"
    snap_path, sha_path = _snapshot_paths(aise_dir)

    if not snap_path.exists():
        return False, "snapshot_missing", None
    if not sha_path.exists():
        return False, "sha_missing", None

    snapshot_text = snap_path.read_text(encoding="utf-8")
    expected_sha = sha_path.read_text(encoding="utf-8").strip()
    actual_sha = _sha256_text(snapshot_text)
    if actual_sha != expected_sha:
        return False, "snapshot_tampered", None

    snapshot = json.loads(snapshot_text)
    _SNAPSHOT_CACHE = snapshot
    _SNAPSHOT_CACHE_KEY = cache_key
    return True, "ok", snapshot


def require_snapshot(project_root: Path, gate_name: str) -> dict[str, Any]:
    """便捷封装：gate 启动调一行；不通过直接 sys.exit(2)。"""
    import sys

    ok, code, snapshot = check_snapshot(project_root)
    if not ok:
        print(f"[AISE-{gate_name}] FAIL: plan snapshot 校验未通过 (code={code})", file=sys.stderr)
        print(f"  项目根: {project_root}", file=sys.stderr)
        print(f"  排查: ls -la {project_root}/.aise/plan.snapshot.*", file=sys.stderr)
        print(f"  恢复: 重新走 /aise 流程的 ExitPlanMode → snapshot 会重新生成", file=sys.stderr)
        sys.exit(2)
    return snapshot  # type: ignore[return-value]
