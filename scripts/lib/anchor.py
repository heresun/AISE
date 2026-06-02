"""Evidence 内容外锚（#8 证据外锚）

把 evidence artifact 的内容指纹独立锚定到 git 对象库（git hash-object -w，写入
.git/objects）+ 一条独立 ref（refs/aise/evidence/<run_id>，reflog append-only 留痕）。

为什么不用 commit：.aise/ 整个被使用方 .gitignore，run 目录提交不进工作树；
git hash-object 是内容寻址，不依赖文件被 tracked、不污染工作树/主分支历史。

威胁模型（诚实标注）：在 Agent 拥有完整 shell 权限的前提下，本地任何方案
（sha256 / git hash-object / ref）都是 **tamper-evident**（可验篡改、留痕），
不是 **tamper-proof**（防篡改）——攻击者能同时改 artifact、anchor.json 与 git 对象库。
本模块目标：把指纹分置到不同存储（.git/objects）+ ref reflog 时间线，提高"同时
篡改多处"的成本并留痕。真正防篡改需远程透明日志（Rekor 等，违背零依赖故暂缓 v4.1）。

无 git 环境优雅降级：anchor_run 返回 status=skipped、verify_anchor 返回放行，绝不阻断主流程。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def git_available(project_root: Path) -> bool:
    try:
        return _git(["rev-parse", "--git-dir"], project_root).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def hash_object(path: Path, project_root: Path, write: bool = False) -> Optional[str]:
    """git hash-object [-w] <path> → blob sha（确定性内容寻址）。失败返回 None。"""
    args = ["hash-object"]
    if write:
        args.append("-w")
    args.append(str(path))
    try:
        r = _git(args, project_root)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _read_evidence_artifacts(run_dir: Path) -> List[str]:
    ev_path = run_dir / "evidence.jsonl"
    if not ev_path.exists():
        return []
    artifacts: List[str] = []
    for line in ev_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ap = rec.get("artifact_path")
        if ap and ap not in artifacts:
            artifacts.append(ap)
    return artifacts


def anchor_run(run_id: str, project_root: Path) -> Dict:
    """对 run 的所有 evidence artifact 做内容锚定，写 anchor.json + 更新独立 ref。"""
    run_dir = project_root / ".aise" / "runs" / run_id
    if not git_available(project_root):
        return {"status": "skipped", "reason": "git unavailable", "run_id": run_id}

    blobs: Dict[str, str] = {}
    missing: List[str] = []
    for rel in _read_evidence_artifacts(run_dir):
        abs_path = project_root / rel
        if not abs_path.exists():
            missing.append(rel)
            continue
        sha = hash_object(abs_path, project_root, write=True)
        if sha:
            blobs[rel] = sha

    ref = f"refs/aise/evidence/{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = run_dir / "anchor.json"
    anchor_path.write_text(
        json.dumps({"run_id": run_id, "ref": ref, "blobs": blobs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 独立 ref 留痕：指向 anchor.json 自身的 blob（reflog append-only 时间线）
    anchor_blob = hash_object(anchor_path, project_root, write=True)
    if anchor_blob:
        _git(["update-ref", ref, anchor_blob], project_root)

    return {
        "status": "anchored",
        "run_id": run_id,
        "anchored": len(blobs),
        "missing": missing,
        "ref": ref,
        "anchor_path": str(anchor_path),
    }


def verify_anchor(run_id: str, project_root: Path) -> Tuple[bool, List[Dict]]:
    """重算 git hash-object 比对 anchor.json。无 git → 放行（降级）。"""
    run_dir = project_root / ".aise" / "runs" / run_id
    anchor_path = run_dir / "anchor.json"
    if not git_available(project_root):
        return True, [{"code": "anchor_skipped", "reason": "git unavailable"}]
    if not anchor_path.exists():
        return False, [{"code": "anchor_missing", "path": str(anchor_path)}]

    data = json.loads(anchor_path.read_text(encoding="utf-8"))
    violations: List[Dict] = []
    for rel, expected_sha in data.get("blobs", {}).items():
        abs_path = project_root / rel
        if not abs_path.exists():
            violations.append({"code": "anchor_artifact_missing", "path": rel})
            continue
        actual_sha = hash_object(abs_path, project_root, write=False)
        if actual_sha != expected_sha:
            violations.append({
                "code": "anchor_mismatch", "path": rel,
                "expected_blob": expected_sha, "actual_blob": actual_sha,
            })
    return len(violations) == 0, violations
