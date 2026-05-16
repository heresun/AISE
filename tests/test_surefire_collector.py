"""scripts/lib/surefire_collector.py 单元测试（v3.2.5 §4.4.5.4）

覆盖：
  - 扫描 target/surefire-reports/*.xml + target/failsafe-reports/*.xml
  - 仅匹配 TEST-*.xml（surefire 命名约定）
  - 同盘 hard-link 优先（节省 IO）
  - 跨盘自动回退 fs.copyFileSync
  - 源/目标双 copy 保留（不删源）
  - 空目录返回空 list
  - 不存在 target/ 静默跳过
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from lib import surefire_collector as sc


SUREFIRE_XML_PASS = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="sample.CalcTest" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="sample.CalcTest" name="testAdd" time="0.001"/>
</testsuite>
"""

SUREFIRE_XML_FAIL = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="sample.CalcTest" tests="1" failures="1" errors="0" skipped="0">
  <testcase classname="sample.CalcTest" name="testForceFail" time="0.002">
    <failure message="forced">expected:&lt;0&gt; but was:&lt;1&gt;</failure>
  </testcase>
</testsuite>
"""

FAILSAFE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="sample.CalcIT" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="sample.CalcIT" name="testIntegration" time="0.5"/>
</testsuite>
"""


def _setup_target(project_root: Path, surefire: dict | None = None, failsafe: dict | None = None) -> None:
    """在 project_root 下铺 target/surefire-reports + failsafe-reports."""
    if surefire:
        sd = project_root / "target" / "surefire-reports"
        sd.mkdir(parents=True, exist_ok=True)
        for name, content in surefire.items():
            (sd / name).write_text(content, encoding="utf-8")
    if failsafe:
        fd = project_root / "target" / "failsafe-reports"
        fd.mkdir(parents=True, exist_ok=True)
        for name, content in failsafe.items():
            (fd / name).write_text(content, encoding="utf-8")


# ----------------------------- 基本扫描 -----------------------------


def test_collect_surefire_single_xml(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(proj, surefire={"TEST-CalcTest.xml": SUREFIRE_XML_PASS})

    result = sc.collect_surefire_xmls(proj, out)
    assert len(result["collected"]) == 1
    rec = result["collected"][0]
    assert rec["src"].endswith("TEST-CalcTest.xml")
    assert rec["dst"].endswith("TEST-CalcTest.xml")
    assert rec["origin"] == "surefire"
    assert Path(rec["dst"]).exists()
    # 源文件保留
    assert Path(rec["src"]).exists()


def test_collect_surefire_multi_xml(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(
        proj,
        surefire={
            "TEST-CalcTest.xml": SUREFIRE_XML_PASS,
            "TEST-OtherTest.xml": SUREFIRE_XML_FAIL,
        },
    )
    result = sc.collect_surefire_xmls(proj, out)
    assert len(result["collected"]) == 2
    names = sorted(Path(r["dst"]).name for r in result["collected"])
    assert names == ["TEST-CalcTest.xml", "TEST-OtherTest.xml"]


def test_collect_surefire_and_failsafe_both(tmp_path: Path) -> None:
    """同时收集 surefire + failsafe，origin 字段区分。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(
        proj,
        surefire={"TEST-CalcTest.xml": SUREFIRE_XML_PASS},
        failsafe={"TEST-CalcIT.xml": FAILSAFE_XML},
    )
    result = sc.collect_surefire_xmls(proj, out)
    assert len(result["collected"]) == 2
    origins = {r["origin"] for r in result["collected"]}
    assert origins == {"surefire", "failsafe"}


def test_collect_skips_non_test_xml(tmp_path: Path) -> None:
    """非 TEST-*.xml（例如 surefire-summary.xml）不应被收集。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    sd = proj / "target" / "surefire-reports"
    sd.mkdir(parents=True)
    (sd / "TEST-CalcTest.xml").write_text(SUREFIRE_XML_PASS, encoding="utf-8")
    (sd / "summary.xml").write_text("<summary/>", encoding="utf-8")
    (sd / "CalcTest.txt").write_text("log", encoding="utf-8")

    result = sc.collect_surefire_xmls(proj, out)
    names = [Path(r["dst"]).name for r in result["collected"]]
    assert names == ["TEST-CalcTest.xml"]


def test_collect_missing_target_returns_empty(tmp_path: Path) -> None:
    """无 target/ 目录静默返回空，不抛异常。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    result = sc.collect_surefire_xmls(proj, out)
    assert result["collected"] == []
    assert result["warnings"] == []


def test_collect_empty_target_returns_empty(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "target" / "surefire-reports").mkdir(parents=True)
    out = tmp_path / "out"
    result = sc.collect_surefire_xmls(proj, out)
    assert result["collected"] == []


# ----------------------------- hard-link 优先 -----------------------------


def test_collect_uses_hard_link_when_same_device(tmp_path: Path) -> None:
    """同盘默认走 hard-link，src/dst 应共享 inode。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"  # 同 tmp_path 父，必同盘
    _setup_target(proj, surefire={"TEST-CalcTest.xml": SUREFIRE_XML_PASS})

    result = sc.collect_surefire_xmls(proj, out)
    rec = result["collected"][0]
    src_stat = Path(rec["src"]).stat()
    dst_stat = Path(rec["dst"]).stat()
    assert src_stat.st_ino == dst_stat.st_ino, "同盘应走 hard-link 共享 inode"
    assert rec["method"] == "hard-link"


def test_collect_falls_back_to_copy_when_link_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟 os.link 抛 OSError → 回退 shutil.copyfile，文件仍落盘。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(proj, surefire={"TEST-CalcTest.xml": SUREFIRE_XML_PASS})

    real_link = os.link

    def fake_link(src, dst):
        raise OSError(18, "Cross-device link")  # EXDEV

    monkeypatch.setattr(os, "link", fake_link)
    result = sc.collect_surefire_xmls(proj, out)
    rec = result["collected"][0]
    assert rec["method"] == "copy"
    assert Path(rec["dst"]).exists()
    # inode 不应相同（copy 是新 inode）
    assert Path(rec["src"]).stat().st_ino != Path(rec["dst"]).stat().st_ino


def test_collect_does_not_delete_source(tmp_path: Path) -> None:
    """v3.2.5 §4.4.5.4 dual copy 保留，源始终在。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(proj, surefire={"TEST-CalcTest.xml": SUREFIRE_XML_PASS})
    src_orig = proj / "target" / "surefire-reports" / "TEST-CalcTest.xml"
    orig_content = src_orig.read_text()

    sc.collect_surefire_xmls(proj, out)

    assert src_orig.exists()
    assert src_orig.read_text() == orig_content


# ----------------------------- naming collision -----------------------------


def test_collect_handles_surefire_failsafe_same_name(tmp_path: Path) -> None:
    """surefire 和 failsafe 各有同名 TEST-Foo.xml → 用 origin 前缀避撞."""
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    _setup_target(
        proj,
        surefire={"TEST-Foo.xml": SUREFIRE_XML_PASS},
        failsafe={"TEST-Foo.xml": FAILSAFE_XML},
    )
    result = sc.collect_surefire_xmls(proj, out)
    assert len(result["collected"]) == 2
    dst_names = sorted(Path(r["dst"]).name for r in result["collected"])
    assert dst_names == ["TEST-Foo.xml", "failsafe-TEST-Foo.xml"]
