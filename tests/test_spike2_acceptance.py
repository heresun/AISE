"""Spike-2 mvn-surefire 闭环验收（v3.2.5 §18.3 Spike-2 横向扩展）

3 条硬指标：
  ① strict Green + Red 双 PASS（targetCovers 桥接 testcase→package="sample"）
  ② 多 XML 收集（hard-link 同 inode）+ Surefire vs Failsafe 同名按
     source_artifact_path 区分（v3.2.5 §4.1 P1-B）
  ③ evidence sha256 篡改检测（mvn-surefire 链路也生效）

环境要求：
  - java （已装）
  - mvn  （Spike-2 需先 brew install maven）
  - tests/fixtures/maven-sample/ 项目

运行：
  pytest tests/test_spike2_acceptance.py -v
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
from lib.target_cover import all_declared_covered


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "maven-sample"
EXPECTED_PACKAGE = "sample"


pytestmark = pytest.mark.skipif(
    shutil.which("mvn") is None or shutil.which("java") is None,
    reason="Spike-2 需要 mvn + java",
)


def _run_aise_event_mvn(
    run_id: str,
    project_root: Path,
    force_fail: bool = False,
) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPTS / "aise_event.py"),
        "--pipe", "mvn-surefire",
        "--project-root", str(project_root),
        "--run-id", run_id,
    ]
    if force_fail:
        cmd += ["--mvn-system-property", "forceFail=true"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not proc.stdout.strip().startswith("{"):
        raise RuntimeError(
            f"aise_event.py 输出异常\nexit={proc.returncode}\n"
            f"stdout={proc.stdout[:1000]}\nstderr={proc.stderr[:1000]}"
        )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def warm_maven_repo() -> None:
    """先在原 fixture 上跑一次 mvn test 预热依赖（避免每个用例都下载 junit-jupiter）。"""
    if shutil.which("mvn") is None:
        return
    subprocess.run(
        ["mvn", "-B", "-q", "dependency:resolve"],
        cwd=str(FIXTURE),
        capture_output=True,
        timeout=600,
    )


@pytest.fixture
def isolated_maven(tmp_path: Path, warm_maven_repo) -> Path:
    dst = tmp_path / "maven-sample"
    shutil.copytree(FIXTURE, dst)
    return dst


# ============================================================
# 硬指标 ①：strict Green + Red 双 PASS，targetCovers 桥接生效
# ============================================================


def test_spike2_strict_green_passes_target_covers(isolated_maven: Path) -> None:
    summary = _run_aise_event_mvn("spike2-acc-green", isolated_maven, force_fail=False)
    assert summary["test_ok"] is True, f"Green 应通过: {summary.get('test_exit_code')}"
    assert summary["junit_ok"] is True
    assert len(summary["collected"]) >= 1, "至少收一个 Surefire XML"
    assert len(summary["actual_test_targets"]) >= 3

    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, missing = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, f"targetCovers 桥接失败: missing={missing}"


def test_spike2_strict_red_still_produces_valid_evidence(isolated_maven: Path) -> None:
    summary = _run_aise_event_mvn("spike2-acc-red", isolated_maven, force_fail=True)
    assert summary["test_ok"] is False, "AISE forceFail=true 应让测试红"
    assert summary["junit_ok"] is True, "Red 时 XML 仍应落盘"
    failed_targets = [t for t in summary["actual_test_targets"] if not t["passed"]]
    assert any(t["id"] == "testForceFailable" for t in failed_targets)

    declared = [{"kind": "package", "id": EXPECTED_PACKAGE}]
    ok, _ = all_declared_covered(summary["actual_test_targets"], declared)
    assert ok is True, "Red 状态下桥接也应生效"


# ============================================================
# 硬指标 ②：多 XML 收集 + hard-link inode 共享
# ============================================================


def test_spike2_collected_xml_uses_hard_link_on_same_device(isolated_maven: Path) -> None:
    summary = _run_aise_event_mvn("spike2-acc-link", isolated_maven, force_fail=False)
    assert len(summary["collected"]) >= 1
    rec = summary["collected"][0]
    src_stat = Path(rec["src"]).stat()
    dst_stat = Path(rec["dst"]).stat()
    # 同 tmp_path 下，APFS 应支持 hard-link
    if rec["method"] == "hard-link":
        assert src_stat.st_ino == dst_stat.st_ino, "hard-link 应共享 inode"
    # 源文件保留（v3.2.5 §4.4.5.4 dual copy）
    assert Path(rec["src"]).exists()


def test_spike2_source_artifact_path_per_testcase(isolated_maven: Path) -> None:
    """每个 testcase 都带 source_artifact_path（v3.2.5 §4.1 provenance），
    且指向已收集 dst 文件。"""
    summary = _run_aise_event_mvn("spike2-acc-prov", isolated_maven, force_fail=False)
    dst_paths = {r["dst"] for r in summary["collected"]}
    for t in summary["actual_test_targets"]:
        assert "source_artifact_path" in t
        assert t["source_artifact_path"] in dst_paths, \
            f"testcase {t['id']} 的 source_artifact_path 不在 collected 列表"


# ============================================================
# 硬指标 ③：evidence 篡改检测
# ============================================================


def test_spike2_evidence_tamper_detected(isolated_maven: Path) -> None:
    summary = _run_aise_event_mvn("spike2-acc-tamper", isolated_maven, force_fail=False)
    evidence_path = Path(summary["evidence_jsonl"])
    assert evidence_path.exists()

    lines = evidence_path.read_text("utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64
    lines[0] = json.dumps(first, ensure_ascii=False)
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_maven)
    assert ok is False
    assert any(v["code"] == "evidence_tampered" for v in violations)


def test_spike2_evidence_clean_passes(isolated_maven: Path) -> None:
    summary = _run_aise_event_mvn("spike2-acc-clean", isolated_maven, force_fail=False)
    evidence_path = Path(summary["evidence_jsonl"])
    ok, violations = ev_lib.verify_evidence(evidence_path, isolated_maven)
    assert ok is True, f"未篡改不应 FAIL: {violations}"
