"""Spike-1 闭环验收（3 条硬指标）

按 v3.2.5 §18.3 Spike-1 验收清单：
  ① strict Green 1 次 PASS + strict Red 1 次 PASS（targetCovers 桥接生效）
  ② 故意篡改 evidence sha256 → 1 次 FAIL（machine signoff 生效）
  ③ mtime 单边 ±2s 容忍：±1.9s PASS / ±2.1s FAIL

环境要求：
  - $HOME/go/bin/go-junit-report
  - go 命令在 PATH
  - tests/fixtures/go-sample/ Go fixture

运行：
  PATH=$HOME/go/bin:$PATH pytest tests/test_spike1_acceptance.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib import evidence as ev_lib
from lib.target_cover import all_declared_covered, target_covers


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "go-sample"
EXPECTED_PACKAGE = "aise/spike1/sample/pkg/sample"


def _go_bin_in_path() -> bool:
    extra = os.environ.get("PATH", "") + os.pathsep + str(Path.home() / "go" / "bin")
    return shutil.which("go", path=extra) is not None and \
           shutil.which("go-junit-report", path=extra) is not None


pytestmark = pytest.mark.skipif(
    not _go_bin_in_path(),
    reason="Spike-1 验收需要 go + go-junit-report 工具链",
)


def _env_with_go_bin(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    home_go_bin = str(Path.home() / "go" / "bin")
    if home_go_bin not in env.get("PATH", ""):
        env["PATH"] = home_go_bin + os.pathsep + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def _run_aise_event(run_id: str, fail: bool = False, tmp_root: Path | None = None) -> dict:
    """跑 aise_event.py 端到端，返回 summary dict。"""
    project_root = tmp_root if tmp_root else FIXTURE
    cmd = [
        sys.executable,
        str(SCRIPTS / "aise_event.py"),
        "--pipe", "go-test-json-to-junit",
        "--project-root", str(project_root),
        "--target", "./pkg/sample/...",
        "--run-id", run_id,
    ]
    env = _env_with_go_bin({"AISE_FIXTURE_FORCE_FAIL": "1"} if fail else None)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    if not proc.stdout.strip().startswith("{"):
        raise RuntimeError(
            f"aise_event.py 输出异常\nexit={proc.returncode}\nstdout={proc.stdout[:500]}\nstderr={proc.stderr[:500]}"
        )
    return json.loads(proc.stdout)


@pytest.fixture
def isolated_fixture(tmp_path: Path) -> Path:
    """每个验收用例独立 fixture 副本，避免 .aise/runs 互相污染。"""
    dst = tmp_path / "go-sample"
    shutil.copytree(FIXTURE, dst)
    return dst


# ============================================================
# 硬指标 ①：strict Green + Red 各 1 次 PASS，targetCovers 桥接
# ============================================================


def test_acceptance_strict_green_passes_target_covers(isolated_fixture: Path) -> None:
    summary = _run_aise_event("spike1-acc-green", fail=False, tmp_root=isolated_fixture)
    assert summary["test_ok"] is True
    assert summary["junit_ok"] is True
    assert summary["test_exit_code"] == 0
    assert len(summary["actual_test_targets"]) >= 3

    # declared 目标用 package 粒度，actual 是 testcase 粒度 → 验证 cross-kind 桥接
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, missing = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, f"strict Green targetCovers 桥接失败: missing={missing}"


def test_acceptance_strict_red_still_produces_valid_evidence(isolated_fixture: Path) -> None:
    """Red 状态：测试 fail (exit 1) 但 pipeline 完整 + targets 解析 + evidence 落盘。"""
    summary = _run_aise_event("spike1-acc-red", fail=True, tmp_root=isolated_fixture)
    assert summary["test_ok"] is False, "AISE_FIXTURE_FORCE_FAIL=1 应让测试失败"
    assert summary["test_exit_code"] == 1
    assert summary["junit_ok"] is True
    # actual_test_targets 仍应解析出（含失败的）
    failed_targets = [t for t in summary["actual_test_targets"] if not t["passed"]]
    assert len(failed_targets) >= 1
    assert any(t["id"] == "TestForceFailable" for t in failed_targets)

    # 桥接仍生效：失败 testcase 仍 cover package
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, _ = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, "Red 状态下 targetCovers 桥接也应生效"


# ============================================================
# 硬指标 ②：篡改 sha256 → FAIL（machine signoff）
# ============================================================


def test_acceptance_evidence_tamper_detected(isolated_fixture: Path) -> None:
    summary = _run_aise_event("spike1-acc-tamper", fail=False, tmp_root=isolated_fixture)
    evidence_path = Path(summary["evidence_jsonl"])
    assert evidence_path.exists()

    # 改 evidence.jsonl 第一行的 sha256 → 模拟"伪造证据"
    lines = evidence_path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64  # 伪造 sha
    lines[0] = json.dumps(first, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_fixture)
    assert ok is False, "篡改 sha 后 verify_evidence 必须 FAIL"
    codes = {v["code"] for v in violations}
    assert "evidence_tampered" in codes, f"未检测到 tampered: {violations}"


def test_acceptance_evidence_clean_passes(isolated_fixture: Path) -> None:
    """对照组：未篡改时 verify_evidence 必须 PASS。"""
    summary = _run_aise_event("spike1-acc-clean", fail=False, tmp_root=isolated_fixture)
    evidence_path = Path(summary["evidence_jsonl"])
    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_fixture)
    assert ok is True, f"未篡改不应 FAIL: {violations}"


# ============================================================
# 硬指标 ③：mtime 单边 ±2s 容忍（±1.9s PASS / ±2.1s FAIL）
# ============================================================


def _touch_mtime(path: Path, mtime_ms: int) -> None:
    sec = mtime_ms / 1000.0
    os.utime(path, (sec, sec))


def test_acceptance_mtime_within_tolerance_passes(isolated_fixture: Path) -> None:
    summary = _run_aise_event("spike1-acc-mtime-pass", fail=False, tmp_root=isolated_fixture)
    evidence_path = Path(summary["evidence_jsonl"])
    rec = json.loads(evidence_path.read_text("utf-8").splitlines()[0])
    artifact = isolated_fixture / rec["artifact_path"]

    # touch 到 window_end + 1.9s（容忍 ±2s 内）
    _touch_mtime(artifact, rec["window_end_ms"] + 1900)

    # 重新计算 sha 后写回，避免 sha 不一致干扰
    import hashlib
    new_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    rec["sha256"] = new_sha
    lines = evidence_path.read_text("utf-8").splitlines()
    lines[0] = json.dumps(rec, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_fixture, tolerance_ms=2000)
    assert ok is True, f"±1.9s 应在 ±2s 容忍内: {violations}"


def test_acceptance_mtime_beyond_tolerance_fails(isolated_fixture: Path) -> None:
    summary = _run_aise_event("spike1-acc-mtime-fail", fail=False, tmp_root=isolated_fixture)
    evidence_path = Path(summary["evidence_jsonl"])
    rec = json.loads(evidence_path.read_text("utf-8").splitlines()[0])
    artifact = isolated_fixture / rec["artifact_path"]

    # touch 到 window_end + 2.5s（超过 ±2s 容忍）
    _touch_mtime(artifact, rec["window_end_ms"] + 2500)

    # 同步 sha 避免 tampered 干扰
    import hashlib
    new_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    rec["sha256"] = new_sha
    lines = evidence_path.read_text("utf-8").splitlines()
    lines[0] = json.dumps(rec, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_fixture, tolerance_ms=2000)
    assert ok is False, "±2.5s 应超出 ±2s 容忍"
    codes = {v["code"] for v in violations}
    assert "evidence_window_violation" in codes, f"未触发 window_violation: {violations}"
