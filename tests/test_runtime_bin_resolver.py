"""PIPE_DEFS preflight_bin / runtime_bin 分离测试（v3.3 P1-1）

Spike-3 教训：
  - jest-junit preflight bin = node（PATH 上），runtime bin = ./node_modules/.bin/jest（fixture 内）
  - cargo-test-junit preflight bin = cargo2junit，runtime 还需要 cargo

设计：
  - PIPE_DEFS 加可选 `runtime_bin` 字段（str | callable(project_root)→str）
  - 缺省时 runtime_bin = preflight bin
  - event_runner.resolve_runtime_bin(pipe_name, project_root) 返回 (ok, info)
    info = {"bin": str|None, "path": str|None, "via": "preflight_default"|"path_lookup"|"project_local"}
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from lib import event_runner as er


# ----------------------------- resolve_runtime_bin -----------------------------


def test_resolve_runtime_bin_unknown_pipe() -> None:
    ok, info = er.resolve_runtime_bin("totally-fake-pipe-xyz", project_root=Path("/tmp"))
    assert ok is False
    assert info["code"] == "pipe_unknown"


def test_resolve_runtime_bin_falls_back_to_preflight_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺 runtime_bin 字段时，等价于 preflight bin（向后兼容）."""
    # go-test-json-to-junit 没 runtime_bin 字段，默认用 bin = go-junit-report
    monkeypatch.setattr(
        shutil, "which",
        lambda b: "/fake/go-junit-report" if b == "go-junit-report" else None,
    )
    ok, info = er.resolve_runtime_bin("go-test-json-to-junit", project_root=Path("/tmp"))
    assert ok is True
    assert info["bin"] == "go-junit-report"
    assert info["path"] == "/fake/go-junit-report"
    assert info["via"] == "preflight_default"


def test_resolve_runtime_bin_explicit_string_overrides_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PIPE_DEFS 显式声明 runtime_bin 字符串 → 解析为 PATH 上该 bin."""
    # 临时加一个 mock pipe
    monkeypatch.setitem(er.PIPE_DEFS, "mock-pipe", {
        "bin": "preflight-only",
        "runtime_bin": "real-runtime",
        "install": {"Darwin": "x", "Linux": "x", "Windows": "x"},
    })
    monkeypatch.setattr(
        shutil, "which",
        lambda b: f"/fake/{b}" if b == "real-runtime" else None,
    )
    ok, info = er.resolve_runtime_bin("mock-pipe", project_root=Path("/tmp"))
    assert ok is True
    assert info["bin"] == "real-runtime"
    assert info["path"] == "/fake/real-runtime"
    assert info["via"] == "path_lookup"


def test_resolve_runtime_bin_project_local_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runtime_bin 是 project_root 相对路径（如 ./node_modules/.bin/jest）→ 直接拼接."""
    fake_jest_dir = tmp_path / "node_modules" / ".bin"
    fake_jest_dir.mkdir(parents=True)
    fake_jest = fake_jest_dir / "jest"
    fake_jest.write_text("#!/bin/sh\necho ok\n")
    fake_jest.chmod(0o755)

    monkeypatch.setitem(er.PIPE_DEFS, "mock-jest", {
        "bin": "node",
        "runtime_bin": "./node_modules/.bin/jest",
        "install": {"Darwin": "x", "Linux": "x", "Windows": "x"},
    })
    ok, info = er.resolve_runtime_bin("mock-jest", project_root=tmp_path)
    assert ok is True
    assert info["path"] == str(fake_jest)
    assert info["via"] == "project_local"


def test_resolve_runtime_bin_project_local_missing_returns_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """relative path 但项目内不存在 → 返回 runtime_bin_missing."""
    monkeypatch.setitem(er.PIPE_DEFS, "mock-missing", {
        "bin": "node",
        "runtime_bin": "./node_modules/.bin/jest",
        "install": {"Darwin": "x", "Linux": "x", "Windows": "x"},
    })
    ok, info = er.resolve_runtime_bin("mock-missing", project_root=tmp_path)
    assert ok is False
    assert info["code"] == "runtime_bin_missing"
    assert "node_modules" in info["expected_path"]


def test_resolve_runtime_bin_callable_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runtime_bin 是 callable → 调用并返回结果."""
    def resolver(project_root):
        # 复杂逻辑：先看 fixture 内，再看 PATH
        local = project_root / "custom_bin"
        if local.exists():
            return str(local)
        return shutil.which("python3") or ""

    monkeypatch.setitem(er.PIPE_DEFS, "mock-callable", {
        "bin": "python3",
        "runtime_bin": resolver,
        "install": {"Darwin": "x", "Linux": "x", "Windows": "x"},
    })
    custom = tmp_path / "custom_bin"
    custom.write_text("#!/bin/sh\necho hi\n")
    custom.chmod(0o755)

    ok, info = er.resolve_runtime_bin("mock-callable", project_root=tmp_path)
    assert ok is True
    assert info["path"] == str(custom)
    assert info["via"] == "callable_resolver"


# ----------------------------- 实际 PIPE_DEFS 配置验证 -----------------------------


def test_jest_junit_resolves_to_project_local_when_present(
    tmp_path: Path,
) -> None:
    """jest-junit 真实配置：项目内 ./node_modules/.bin/jest 存在 → 项目优先."""
    fake_jest_dir = tmp_path / "node_modules" / ".bin"
    fake_jest_dir.mkdir(parents=True)
    fake_jest = fake_jest_dir / "jest"
    fake_jest.write_text("#!/bin/sh\necho ok\n")
    fake_jest.chmod(0o755)

    ok, info = er.resolve_runtime_bin("jest-junit", project_root=tmp_path)
    assert ok is True
    assert info["path"] == str(fake_jest)
    assert info["via"] == "project_local"


def test_jest_junit_fallback_to_npx_via_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """jest-junit 真实配置：项目内无 jest → 抛 runtime_bin_missing
    （避免 npx 联网拉远端 jest 的不确定性）."""
    ok, info = er.resolve_runtime_bin("jest-junit", project_root=tmp_path)
    assert ok is False
    assert info["code"] == "runtime_bin_missing"


def test_cargo_test_junit_runtime_is_cargo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cargo-test-junit 真实配置：runtime 是 cargo（不是 cargo2junit）."""
    monkeypatch.setattr(
        shutil, "which",
        lambda b: f"/fake/{b}" if b in ("cargo", "cargo2junit") else None,
    )
    ok, info = er.resolve_runtime_bin("cargo-test-junit", project_root=Path("/tmp"))
    assert ok is True
    assert info["bin"] == "cargo"
    assert info["path"] == "/fake/cargo"
