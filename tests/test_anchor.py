"""Evidence 内容外锚测试（#8 证据外锚）

锚定用 git hash-object（内容寻址，写入 .git/objects），与 evidence.jsonl 的 sha256
分置不同存储，提高篡改成本 + 独立留痕。诚实定位：tamper-evident，非 tamper-proof。

覆盖：
  - 无 git 环境 → 优雅降级（skipped，不阻断）
  - 锚定写出 anchor.json（含 git blob sha）
  - 未篡改 → verify_anchor 通过
  - 篡改 artifact → verify_anchor 报 anchor_mismatch
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from lib import anchor as anchor_lib  # noqa: E402


def _git(args, cwd: Path):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@example.com"], tmp_path)
    _git(["config", "user.name", "tester"], tmp_path)
    return tmp_path


def _setup_run(tmp_path: Path, artifact_rel: str = "art.xml") -> Path:
    run_dir = tmp_path / ".aise" / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / artifact_rel).write_text("<testsuite/>", encoding="utf-8")
    ev = {
        "runner": "pytest", "artifact_path": artifact_rel, "sha256": "x",
        "mtime_ms": 0, "window_start_ms": 0, "window_end_ms": 0,
        "bytes": 0, "source": "junit_xml", "ok": True,
    }
    (run_dir / "evidence.jsonl").write_text(json.dumps(ev) + "\n", encoding="utf-8")
    return run_dir


def test_anchor_run_skips_without_git(tmp_path: Path) -> None:
    _setup_run(tmp_path)
    result = anchor_lib.anchor_run("r1", tmp_path)
    assert result["status"] == "skipped"


def test_anchor_run_writes_anchor_json(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_dir = _setup_run(tmp_path)
    result = anchor_lib.anchor_run("r1", tmp_path)
    assert result["status"] == "anchored"
    anchor_json = run_dir / "anchor.json"
    assert anchor_json.exists()
    data = json.loads(anchor_json.read_text("utf-8"))
    assert "art.xml" in data["blobs"]
    assert len(data["blobs"]["art.xml"]) == 40  # git SHA-1 hex


def test_verify_anchor_passes_when_untouched(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _setup_run(tmp_path)
    anchor_lib.anchor_run("r1", tmp_path)
    ok, violations = anchor_lib.verify_anchor("r1", tmp_path)
    assert ok
    assert violations == []


def test_verify_anchor_detects_tampering(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _setup_run(tmp_path)
    anchor_lib.anchor_run("r1", tmp_path)
    (tmp_path / "art.xml").write_text("<TAMPERED/>", encoding="utf-8")
    ok, violations = anchor_lib.verify_anchor("r1", tmp_path)
    assert not ok
    assert any(v["code"] == "anchor_mismatch" for v in violations)


def test_verify_anchor_detects_missing_artifact(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _setup_run(tmp_path)
    anchor_lib.anchor_run("r1", tmp_path)
    (tmp_path / "art.xml").unlink()
    ok, violations = anchor_lib.verify_anchor("r1", tmp_path)
    assert not ok
    assert any(v["code"] == "anchor_artifact_missing" for v in violations)


def test_aise_verify_evidence_runs_anchor_check_e2e(tmp_path: Path) -> None:
    """端到端：真实跑 aise_verify.py --verify-evidence，锚定后篡改 → 门禁拦截 + 走了 anchor 校验。"""
    import time

    from lib import evidence as ev_lib

    _init_repo(tmp_path)
    run_id = "rE2E"
    run_dir = tmp_path / ".aise" / "runs" / run_id
    run_dir.mkdir(parents=True)
    art = run_dir / "art.xml"
    art.write_text("<testsuite/>", encoding="utf-8")

    now = int(time.time() * 1000)
    ev = ev_lib.collect_artifact(
        art, "pytest", now - 1000, now + 1000, "junit_xml", True, tmp_path
    )
    ev_lib.write_evidence([ev], tmp_path, run_id=run_id)
    anchor_lib.anchor_run(run_id, tmp_path)

    # 未篡改：--verify-evidence 应通过且打印外锚校验
    good = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "aise_verify.py"),
         "--project-root", str(tmp_path), "--verify-evidence"],
        capture_output=True, text=True, timeout=30,
    )
    assert good.returncode == 0, f"未篡改应通过: {good.stdout}\n{good.stderr}"
    assert "内容外锚校验通过" in good.stdout

    # 篡改 artifact → 门禁必须拦截
    art.write_text("<TAMPERED/>", encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "aise_verify.py"),
         "--project-root", str(tmp_path), "--verify-evidence"],
        capture_output=True, text=True, timeout=30,
    )
    assert bad.returncode == 1, f"篡改应被拦截: {bad.stdout}"
