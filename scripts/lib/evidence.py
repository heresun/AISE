"""Evidence artifact 签收链

每个 runner 跑完产出 evidence artifact（JUnit XML / stdout 转储 等），
write_evidence() 把 (path, sha256, mtime, source, runner) 记到 .aise/runs/<run_id>/evidence.jsonl。

verify_evidence() 重新读取并校验所有 artifact 内容 hash 未变 + mtime 落在生成窗口内，
用于第二阶段的 aise-ce-review 等下游 gate，让"通过判定"从信任 Agent 自报 → 机器签收。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


MTIME_TOLERANCE_MS = 2000  # ±2s 默认容忍（NTFS/HFS+ 精度差异）


@dataclass
class Evidence:
    runner: str           # "Maven Test" / "pytest" / "npm test" 等
    artifact_path: str    # 相对项目根的路径
    sha256: str
    mtime_ms: int         # 整数毫秒
    window_start_ms: int  # runner 开始时间
    window_end_ms: int    # runner 结束时间
    bytes: int
    source: str           # "junit_xml" / "stdout_dump" / "exit_code"
    ok: bool


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _mtime_ms(path: Path) -> int:
    return int(path.stat().st_mtime * 1000)


def collect_artifact(
    path: Path,
    runner: str,
    window_start_ms: int,
    window_end_ms: int,
    source: str,
    ok: bool,
    project_root: Path,
) -> Evidence | None:
    """对单个 artifact 文件签收。文件不存在返回 None（不报错——某些 runner 不产出 XML）"""
    if not path.exists() or not path.is_file():
        return None
    try:
        rel = str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        rel = str(path.resolve())
    return Evidence(
        runner=runner,
        artifact_path=rel,
        sha256=_sha256_file(path),
        mtime_ms=_mtime_ms(path),
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        bytes=path.stat().st_size,
        source=source,
        ok=ok,
    )


def write_evidence(evidences: Iterable[Evidence], project_root: Path, run_id: str | None = None) -> Path:
    """追加写入 evidence.jsonl。run_id 缺省时用 ISO 时间戳"""
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = project_root / ".aise" / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = runs_dir / "evidence.jsonl"
    with evidence_path.open("a", encoding="utf-8") as f:
        for ev in evidences:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")
    return evidence_path


def verify_evidence(evidence_path: Path, project_root: Path, tolerance_ms: int = MTIME_TOLERANCE_MS) -> tuple[bool, list[dict]]:
    """重新校验 evidence.jsonl 中每条记录：
       - 文件仍存在
       - sha256 未变（evidence_tampered）
       - mtime 仍在 [window_start - tol, window_end + tol] 内（window_violation）
    返回 (all_ok, list_of_violation_dicts)
    """
    if not evidence_path.exists():
        return False, [{"code": "evidence_missing", "path": str(evidence_path)}]

    violations = []
    for lineno, line in enumerate(evidence_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            violations.append({"code": "evidence_json_invalid", "line": lineno, "err": str(e)})
            continue

        artifact = project_root / rec["artifact_path"]
        if not artifact.exists():
            violations.append({"code": "evidence_artifact_missing", "line": lineno, "path": rec["artifact_path"]})
            continue

        actual_sha = _sha256_file(artifact)
        if actual_sha != rec["sha256"]:
            violations.append({
                "code": "evidence_tampered",
                "line": lineno,
                "path": rec["artifact_path"],
                "expected_sha256": rec["sha256"],
                "actual_sha256": actual_sha,
            })
            continue

        actual_mtime = _mtime_ms(artifact)
        if actual_mtime < rec["window_start_ms"] - tolerance_ms or actual_mtime > rec["window_end_ms"] + tolerance_ms:
            violations.append({
                "code": "evidence_window_violation",
                "line": lineno,
                "path": rec["artifact_path"],
                "actual_mtime_ms": actual_mtime,
                "window_start_ms": rec["window_start_ms"],
                "window_end_ms": rec["window_end_ms"],
                "tolerance_ms": tolerance_ms,
            })

    return len(violations) == 0, violations


def latest_run_dir(project_root: Path) -> Path | None:
    runs = project_root / ".aise" / "runs"
    if not runs.exists():
        return None
    children = sorted([d for d in runs.iterdir() if d.is_dir()], reverse=True)
    return children[0] if children else None
