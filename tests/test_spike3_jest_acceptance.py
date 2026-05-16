"""Spike-3 jest-junit 闭环验收。"""
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
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "jest-sample"
EXPECTED_PACKAGE = "calc"  # jest-junit 用顶层 describe 名作 suite name


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FIXTURE / "node_modules" / ".bin" / "jest").exists(),
    reason="Spike-3 jest 链路需要 node + fixture 内 npm install",
)


def _run_aise_event_jest(run_id: str, project_root: Path, force_fail: bool = False) -> dict:
    cmd = [
        sys.executable, str(SCRIPTS / "aise_event.py"),
        "--pipe", "jest-junit",
        "--project-root", str(project_root),
        "--run-id", run_id,
    ]
    env = os.environ.copy()
    if force_fail:
        env["AISE_FIXTURE_FORCE_FAIL"] = "1"
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    if not proc.stdout.strip().startswith("{"):
        raise RuntimeError(f"aise_event.py 输出异常 exit={proc.returncode}\n{proc.stdout[:500]}\n{proc.stderr[:500]}")
    return json.loads(proc.stdout)


@pytest.fixture
def isolated_jest(tmp_path: Path) -> Path:
    """jest fixture 副本——node_modules 用符号链接节省时间。"""
    dst = tmp_path / "jest-sample"
    dst.mkdir()
    for item in FIXTURE.iterdir():
        if item.name == "node_modules":
            os.symlink(item.resolve(), dst / "node_modules")
        elif item.name == ".aise":
            continue
        elif item.is_dir():
            shutil.copytree(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)
    return dst


def test_spike3_jest_green_passes_target_covers(isolated_jest: Path) -> None:
    summary = _run_aise_event_jest("spike3-jest-green", isolated_jest)
    assert summary["test_ok"] is True, f"Green: exit={summary['test_exit_code']}"
    assert summary["junit_ok"] is True
    assert len(summary["actual_test_targets"]) >= 3
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, missing = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, f"targetCovers 桥接失败: missing={missing}"


def test_spike3_jest_red_still_produces_valid_evidence(isolated_jest: Path) -> None:
    summary = _run_aise_event_jest("spike3-jest-red", isolated_jest, force_fail=True)
    assert summary["test_ok"] is False
    assert summary["junit_ok"] is True
    failed = [t for t in summary["actual_test_targets"] if not t["passed"]]
    assert len(failed) >= 1
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, _ = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True


def test_spike3_jest_source_artifact_path_set(isolated_jest: Path) -> None:
    summary = _run_aise_event_jest("spike3-jest-prov", isolated_jest)
    junit_xml = summary["junit_xml"]
    for t in summary["actual_test_targets"]:
        assert t["source_artifact_path"] == junit_xml


def test_spike3_jest_evidence_tamper_detected(isolated_jest: Path) -> None:
    summary = _run_aise_event_jest("spike3-jest-tamper", isolated_jest)
    evidence_path = Path(summary["evidence_jsonl"])
    lines = evidence_path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64
    lines[0] = json.dumps(first, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_jest)
    assert ok is False
    assert any(v["code"] == "evidence_tampered" for v in violations)
