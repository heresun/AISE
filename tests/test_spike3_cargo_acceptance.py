"""Spike-3 cargo-test-junit 闭环验收。"""
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
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "cargo-sample"
EXPECTED_PACKAGE = "tests"  # cargo2junit testcase.classname = "tests"


def _cargo_ready() -> bool:
    cargo_paths = [Path.home() / ".cargo" / "bin" / "cargo", shutil.which("cargo")]
    cj_paths = [Path.home() / ".cargo" / "bin" / "cargo2junit", shutil.which("cargo2junit")]
    return any(p and Path(p).exists() for p in cargo_paths) and \
           any(p and Path(p).exists() for p in cj_paths)


pytestmark = pytest.mark.skipif(not _cargo_ready(), reason="Spike-3 cargo 链路需要 cargo + cargo2junit")


def _env_with_cargo() -> dict:
    env = os.environ.copy()
    cargo_bin_dir = str(Path.home() / ".cargo" / "bin")
    if cargo_bin_dir not in env.get("PATH", ""):
        env["PATH"] = cargo_bin_dir + os.pathsep + env.get("PATH", "")
    return env


def _run_aise_event_cargo(run_id: str, project_root: Path, force_fail: bool = False) -> dict:
    cmd = [
        sys.executable, str(SCRIPTS / "aise_event.py"),
        "--pipe", "cargo-test-junit",
        "--project-root", str(project_root),
        "--run-id", run_id,
    ]
    env = _env_with_cargo()
    if force_fail:
        env["AISE_FIXTURE_FORCE_FAIL"] = "1"
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    if not proc.stdout.strip().startswith("{"):
        raise RuntimeError(f"aise_event.py 输出异常 exit={proc.returncode}\n{proc.stdout[:500]}\n{proc.stderr[:500]}")
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def warm_cargo_build() -> None:
    """先预编译，避免每个用例都重编。"""
    env = _env_with_cargo()
    subprocess.run(
        ["cargo", "build", "--tests"],
        cwd=str(FIXTURE),
        env=env,
        capture_output=True,
        timeout=300,
    )


@pytest.fixture
def isolated_cargo(tmp_path: Path, warm_cargo_build) -> Path:
    """cargo fixture 副本——target/ 用符号链接共享编译产物."""
    dst = tmp_path / "cargo-sample"
    dst.mkdir()
    for item in FIXTURE.iterdir():
        if item.name == "target":
            if item.exists():
                os.symlink(item.resolve(), dst / "target")
        elif item.name == ".aise":
            continue
        elif item.is_dir():
            shutil.copytree(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)
    return dst


def test_spike3_cargo_green_passes_target_covers(isolated_cargo: Path) -> None:
    summary = _run_aise_event_cargo("spike3-cargo-green", isolated_cargo)
    assert summary["test_ok"] is True, f"Green: exit={summary['test_exit_code']}"
    assert summary["junit_ok"] is True
    assert len(summary["actual_test_targets"]) >= 3
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, missing = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, f"targetCovers 桥接失败: missing={missing}"


def test_spike3_cargo_red_still_produces_valid_evidence(isolated_cargo: Path) -> None:
    summary = _run_aise_event_cargo("spike3-cargo-red", isolated_cargo, force_fail=True)
    assert summary["test_ok"] is False
    assert summary["junit_ok"] is True
    failed = [t for t in summary["actual_test_targets"] if not t["passed"]]
    assert len(failed) >= 1
    assert any(t["id"] == "test_force_failable" for t in failed)
    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, _ = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True


def test_spike3_cargo_evidence_tamper_detected(isolated_cargo: Path) -> None:
    summary = _run_aise_event_cargo("spike3-cargo-tamper", isolated_cargo)
    evidence_path = Path(summary["evidence_jsonl"])
    lines = evidence_path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64
    lines[0] = json.dumps(first, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_cargo)
    assert ok is False
    assert any(v["code"] == "evidence_tampered" for v in violations)
