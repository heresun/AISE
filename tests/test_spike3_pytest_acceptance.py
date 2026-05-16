"""Spike-3 pytest-junitxml 闭环验收。

3 条硬指标：
  ① strict Green + Red 双 PASS（targetCovers 桥接 testcase→package="tests"）
  ② source_artifact_path provenance（每个 testcase 携带 JUnit XML 路径）
  ③ evidence sha256 篡改检测在 pytest 链路也生效
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lib import evidence as ev_lib
from lib.target_cover import all_declared_covered


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "python-sample"
EXPECTED_PACKAGE = "tests"  # pytest classname 是 "tests.test_calc"，rsplit('.',1)[0] = "tests"


pytestmark = pytest.mark.skipif(
    shutil.which("pytest") is None and shutil.which("python3") is None,
    reason="Spike-3 pytest 链路需要 pytest 或 python3",
)


def _run_aise_event_pytest(
    run_id: str,
    project_root: Path,
    force_fail: bool = False,
) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPTS / "aise_event.py"),
        "--pipe", "pytest-junitxml",
        "--project-root", str(project_root),
        "--run-id", run_id,
    ]
    env = os.environ.copy()
    if force_fail:
        env["AISE_FIXTURE_FORCE_FAIL"] = "1"
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    if not proc.stdout.strip().startswith("{"):
        raise RuntimeError(
            f"aise_event.py 输出异常\nexit={proc.returncode}\n"
            f"stdout={proc.stdout[:500]}\nstderr={proc.stderr[:500]}"
        )
    return json.loads(proc.stdout)


@pytest.fixture
def isolated_python(tmp_path: Path) -> Path:
    dst = tmp_path / "python-sample"
    shutil.copytree(FIXTURE, dst)
    return dst


# ============================================================
# 硬指标 ①：Green + Red 双 PASS，targetCovers 桥接
# ============================================================


def test_spike3_pytest_green_passes_target_covers(isolated_python: Path) -> None:
    summary = _run_aise_event_pytest("spike3-pytest-green", isolated_python)
    assert summary["test_ok"] is True, f"Green 应通过: exit={summary.get('test_exit_code')}"
    assert summary["junit_ok"] is True
    assert len(summary["actual_test_targets"]) >= 3

    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, missing = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, f"targetCovers 桥接失败: missing={missing}"


def test_spike3_pytest_red_still_produces_valid_evidence(isolated_python: Path) -> None:
    summary = _run_aise_event_pytest("spike3-pytest-red", isolated_python, force_fail=True)
    assert summary["test_ok"] is False, "AISE_FIXTURE_FORCE_FAIL=1 应让测试红"
    assert summary["junit_ok"] is True, "Red 时 XML 仍应落盘"
    failed = [t for t in summary["actual_test_targets"] if not t["passed"]]
    assert any(t["id"] == "test_force_failable" for t in failed)

    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, _ = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True


# ============================================================
# 硬指标 ②：source_artifact_path provenance
# ============================================================


def test_spike3_pytest_source_artifact_path_set(isolated_python: Path) -> None:
    summary = _run_aise_event_pytest("spike3-pytest-prov", isolated_python)
    junit_xml = summary["junit_xml"]
    for t in summary["actual_test_targets"]:
        assert t["source_artifact_path"] == junit_xml, \
            f"testcase {t['id']} source_artifact_path 不对"


# ============================================================
# 硬指标 ③：evidence 篡改检测
# ============================================================


def test_spike3_pytest_evidence_tamper_detected(isolated_python: Path) -> None:
    summary = _run_aise_event_pytest("spike3-pytest-tamper", isolated_python)
    evidence_path = Path(summary["evidence_jsonl"])
    lines = evidence_path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64
    lines[0] = json.dumps(first, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_python)
    assert ok is False
    assert any(v["code"] == "evidence_tampered" for v in violations)


def test_spike3_pytest_evidence_clean_passes(isolated_python: Path) -> None:
    summary = _run_aise_event_pytest("spike3-pytest-clean", isolated_python)
    evidence_path = Path(summary["evidence_jsonl"])
    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_python)
    assert ok is True, f"未篡改不应 FAIL: {violations}"
