"""scripts/lib/event_runner.py 单元测试（v3.2.5 §4.4.5）

覆盖：
  - preflight_pipe 已知 pipe + 工具已装 → ok
  - preflight_pipe 已知 pipe + 工具缺失 → 平台指引 + exit 127 语义
  - preflight_pipe 未知 pipe → pipe_unknown
  - defense_in_depth_check target 在白名单 → ok
  - defense_in_depth_check target 不在白名单 → pipe_target_breached_manifest
  - 平台检测复用 preflight.detect_platform
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

import pytest

from lib import event_runner as er


# ----------------------------- preflight_pipe -----------------------------


def test_preflight_pipe_unknown_returns_pipe_unknown() -> None:
    ok, info = er.preflight_pipe("totally-fake-pipe-xyz")
    assert ok is False
    assert info["code"] == "pipe_unknown"
    assert info["name"] == "totally-fake-pipe-xyz"


def test_preflight_pipe_missing_tool_returns_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 go-junit-report 不在 PATH → 应给出平台特定安装指引"""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    ok, info = er.preflight_pipe("go-test-json-to-junit")
    assert ok is False
    assert info["code"] == "pipe_tool_missing"
    assert info["bin"] == "go-junit-report"
    assert "install_hint" in info and info["install_hint"]
    assert "go install" in info["install_hint"]  # 跨平台都用 go install


def test_preflight_pipe_known_pipe_with_tool_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 which 找到 go-junit-report → ok"""
    monkeypatch.setattr(
        shutil,
        "which",
        lambda b: "/fake/path/go-junit-report" if b == "go-junit-report" else None,
    )
    ok, info = er.preflight_pipe("go-test-json-to-junit")
    assert ok is True
    assert info["bin"] == "go-junit-report"
    assert info["found"] == "/fake/path/go-junit-report"


def test_preflight_pipe_install_hint_per_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三平台都应返回非空指引，且 go install 命令一致"""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    for pf in ("Darwin", "Linux", "Windows"):
        monkeypatch.setattr(er, "detect_platform", lambda pf=pf: pf)
        ok, info = er.preflight_pipe("go-test-json-to-junit")
        assert ok is False
        assert info["platform"] == pf
        assert info["install_hint"].startswith("go install")


# ----------------------------- defense_in_depth -----------------------------


def test_defense_in_depth_allowed_target_passes() -> None:
    targets = ["./pkg/sample/...", "./internal/auth/..."]
    allowed = ["./pkg/**", "./internal/**"]
    ok, info = er.defense_in_depth_check(targets, allowed)
    assert ok is True
    assert info == {}


def test_defense_in_depth_breached_target_blocked() -> None:
    targets = ["./pkg/sample/...", "./../../etc/passwd"]
    allowed = ["./pkg/**"]
    ok, info = er.defense_in_depth_check(targets, allowed)
    assert ok is False
    assert info["code"] == "pipe_target_breached_manifest"
    assert info["target"] == "./../../etc/passwd"
    assert info["allowed"] == allowed


def test_defense_in_depth_empty_allowed_blocks_all() -> None:
    ok, info = er.defense_in_depth_check(["./anything"], [])
    assert ok is False
    assert info["code"] == "pipe_target_breached_manifest"


def test_defense_in_depth_empty_targets_passes() -> None:
    """没有 target 时（如 run 全部）允许通过——白名单不约束空集"""
    ok, info = er.defense_in_depth_check([], ["./pkg/**"])
    assert ok is True


# ----------------------------- exit code helpers -----------------------------


def test_pipe_missing_exit_code_is_127() -> None:
    """与 aise_run.cjs Python preflight 一致：缺工具退出 127（POSIX command-not-found）"""
    assert er.EXIT_CODE_TOOL_MISSING == 127


def test_pipe_breached_exit_code_is_2() -> None:
    """白名单违反 → 状态异常（exit 2）"""
    assert er.EXIT_CODE_TARGET_BREACHED == 2


# ----------------------------- PIPE_DEFS schema -----------------------------


def test_pipe_defs_contains_go_pipe() -> None:
    assert "go-test-json-to-junit" in er.PIPE_DEFS
    g = er.PIPE_DEFS["go-test-json-to-junit"]
    assert g["bin"] == "go-junit-report"
    assert set(g["install"].keys()) >= {"Darwin", "Linux", "Windows"}


def test_pipe_defs_all_entries_have_install_for_three_platforms() -> None:
    for name, dep in er.PIPE_DEFS.items():
        assert "bin" in dep, f"{name} 缺 bin"
        assert "install" in dep, f"{name} 缺 install"
        for pf in ("Darwin", "Linux", "Windows"):
            assert pf in dep["install"], f"{name} 缺 {pf} 安装指引"
            assert dep["install"][pf], f"{name}.{pf} 指引为空"
