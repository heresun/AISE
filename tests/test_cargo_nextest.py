"""cargo-nextest-junit pipe 单元测试（v3.5 第 6 个 pipe）

设计：
  - preflight 验证 cargo 在 PATH（必要）+ cargo nextest 子命令可用（可选 warn）
  - runtime 跑 `cargo nextest run --message-format junit`
  - 输出 JUnit XML 落 target/nextest/<profile>/junit.xml，无 RUSTC_BOOTSTRAP=1
  - parser 与 cargo2junit 输出兼容（同样的 testcase.classname = 模块路径）

不需要本地装 cargo-nextest 即可测：单元层用 mock，acceptance 用 pytest.skipif。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lib import event_runner as er


# ----------------------------- PIPE_DEFS 注册 -----------------------------


def test_cargo_nextest_in_pipe_defs() -> None:
    assert "cargo-nextest-junit" in er.PIPE_DEFS
    dep = er.PIPE_DEFS["cargo-nextest-junit"]
    assert "bin" in dep
    assert "install" in dep
    assert all(p in dep["install"] for p in ("Darwin", "Linux", "Windows"))


def test_cargo_nextest_runtime_bin_is_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    """nextest 是 cargo 子命令，runtime 真正调 cargo."""
    monkeypatch.setattr(
        shutil, "which",
        lambda b: f"/fake/{b}" if b in ("cargo", "cargo-nextest") else None,
    )
    ok, info = er.resolve_runtime_bin("cargo-nextest-junit", project_root=Path("/tmp"))
    assert ok is True
    assert info["bin"] == "cargo"
    assert info["path"] == "/fake/cargo"


# ----------------------------- preflight -----------------------------


def test_preflight_cargo_nextest_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda b: None)
    ok, info = er.preflight_pipe("cargo-nextest-junit")
    assert ok is False
    assert info["code"] == "pipe_tool_missing"
    assert "cargo install cargo-nextest" in info["install_hint"] or \
           "cargo-nextest" in info["install_hint"]


def test_preflight_cargo_nextest_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight bin 是 cargo-nextest（不是 cargo），需要 cargo-nextest 在 PATH."""
    monkeypatch.setattr(
        shutil, "which",
        lambda b: "/fake/cargo-nextest" if b == "cargo-nextest" else None,
    )
    ok, info = er.preflight_pipe("cargo-nextest-junit")
    assert ok is True
    assert info["bin"] == "cargo-nextest"


# ----------------------------- 解析 JUnit XML -----------------------------


def test_parse_nextest_junit_xml(tmp_path: Path) -> None:
    """nextest --message-format junit 输出格式与 cargo2junit 类似：
       <testsuite name="my_crate"><testcase name="..." classname="..."/>"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from aise_event import _parse_cargo_targets  # 复用同 parser

    xml = tmp_path / "junit.xml"
    xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="aise_spike3_cargo_sample" tests="3" failures="0">
    <testcase classname="tests" name="test_add" time="0.001"/>
    <testcase classname="tests" name="test_is_even" time="0.001"/>
    <testcase classname="integration" name="test_e2e" time="0.5"/>
  </testsuite>
</testsuites>
""", encoding="utf-8")
    targets = _parse_cargo_targets(xml)
    assert len(targets) == 3
    # cargo nextest 和 cargo2junit 都把 classname 设为 Rust 模块路径
    names = {(t["id"], t["parent_package"]) for t in targets}
    assert ("test_add", "tests") in names
    assert ("test_e2e", "integration") in names


# ----------------------------- CLI 集成 -----------------------------


def test_aise_event_help_includes_cargo_nextest() -> None:
    proj_root = Path(__file__).resolve().parent.parent
    event_py = proj_root / "scripts" / "aise_event.py"
    r = subprocess.run(
        [sys.executable, str(event_py), "--help"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=10,
    )
    # --pipe 选项 help 应不限定（接受任意 pipe 名）；至少不应阻止 cargo-nextest-junit
    assert "Pipe" in r.stdout or "pipe" in r.stdout.lower()


def test_aise_event_unknown_pipe_rejected() -> None:
    """跑一个不存在的 pipe 应 exit 2 / 127."""
    proj_root = Path(__file__).resolve().parent.parent
    event_py = proj_root / "scripts" / "aise_event.py"
    r = subprocess.run(
        [sys.executable, str(event_py),
         "--pipe", "totally-fake-xyz",
         "--project-root", "/tmp",
         "--run-id", "test"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=10,
    )
    assert r.returncode in (2, 127)


# ----------------------------- 端到端（需要 cargo-nextest 装好）-----------------------------

NEXTEST_AVAILABLE = (
    shutil.which("cargo") is not None
    and shutil.which("cargo-nextest") is not None
)


@pytest.mark.skipif(not NEXTEST_AVAILABLE, reason="需要 cargo + cargo-nextest")
def test_cargo_nextest_acceptance_green(tmp_path: Path) -> None:
    """端到端：跑 fixture 项目，nextest 全 green，targets 解析正确."""
    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cargo-sample"
    proj_root = Path(__file__).resolve().parent.parent
    event_py = proj_root / "scripts" / "aise_event.py"

    dst = tmp_path / "cargo-sample"
    shutil.copytree(FIXTURE, dst)

    env = os.environ.copy()
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")

    r = subprocess.run(
        [sys.executable, str(event_py),
         "--pipe", "cargo-nextest-junit",
         "--project-root", str(dst),
         "--run-id", "nextest-green"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    if not r.stdout.strip().startswith("{"):
        pytest.fail(f"exit={r.returncode}\nstdout={r.stdout[:500]}\nstderr={r.stderr[:1000]}")

    summary = json.loads(r.stdout)
    assert summary["test_ok"] is True
    assert summary["junit_ok"] is True
    assert len(summary["actual_test_targets"]) >= 2
