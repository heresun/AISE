"""lib/preflight.py 直接单元测试（v3.6 补充）

preflight 是通用工具存在性检查 + 平台安装指引，原本仅被 aise_verify 间接使用。
本测试直接覆盖 TOOL_DEPS 注册、alt_bins 优先级、preflight_or_exit 行为。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lib import preflight as pf


def test_detect_platform_returns_known() -> None:
    p = pf.detect_platform()
    assert p in {"Darwin", "Linux", "Windows"}


def test_preflight_unknown_tool() -> None:
    ok, info = pf.preflight("totally-fake-xyz")
    assert ok is False
    assert info["code"] == "preflight_unknown_tool"
    assert info["tool_key"] == "totally-fake-xyz"


def test_preflight_existing_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    """mvn 在 PATH → ok."""
    monkeypatch.setattr(
        shutil, "which",
        lambda b: f"/fake/{b}" if b == "mvn" else None,
    )
    ok, info = pf.preflight("mvn")
    assert ok is True
    assert info["code"] == "ok"
    assert info["found"] == "/fake/mvn"
    assert info["via"] == "path"


def test_preflight_missing_returns_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """mvn 不在 PATH → fail + 平台特定 install 命令."""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    ok, info = pf.preflight("mvn")
    assert ok is False
    assert info["code"] == "tool_missing"
    assert info["bin"] == "mvn"
    assert info["platform"] in {"Darwin", "Linux", "Windows"}
    assert info["install"]


def test_preflight_alt_bins_wrapper_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """./gradlew 存在 → 优先用 wrapper（不走 PATH 上的 gradle）."""
    # 模拟 PATH 上没 gradle，但项目内有 ./gradlew
    monkeypatch.setattr(shutil, "which", lambda b: None)
    (tmp_path / "gradlew").write_text("#!/bin/sh\necho ok\n")
    (tmp_path / "gradlew").chmod(0o755)
    ok, info = pf.preflight("gradle", project_root=tmp_path)
    assert ok is True
    assert info["via"] == "wrapper"
    assert "gradlew" in info["found"]


def test_preflight_alt_bins_python_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest 通过 python -m pytest 兜底."""
    # PATH 上无 pytest，但 python3 存在且 pytest 模块可用
    monkeypatch.setattr(shutil, "which",
                        lambda b: "/usr/bin/python3" if b == "python3" else None)
    monkeypatch.setattr(pf, "_python_module_available", lambda py, mod: True)
    ok, info = pf.preflight("pytest")
    assert ok is True
    assert info["via"] == "alt"
    assert "python3 -m pytest" in info["found"]


def test_preflight_optional_tool_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """optional 工具（如 ruff）缺失时 info.optional=True，但仍 fail."""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    ok, info = pf.preflight("ruff")
    assert ok is False
    assert info.get("optional") is True


def test_preflight_or_exit_returns_found_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight_or_exit 成功时返回 bin 路径."""
    monkeypatch.setattr(
        shutil, "which",
        lambda b: "/usr/bin/mvn" if b == "mvn" else None,
    )
    found = pf.preflight_or_exit("mvn")
    assert found == "/usr/bin/mvn"


def test_preflight_or_exit_exits_on_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight_or_exit 缺工具时 sys.exit(127)."""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    with pytest.raises(SystemExit) as exc_info:
        pf.preflight_or_exit("mvn")
    assert exc_info.value.code == 127


def test_preflight_or_exit_optional_warns_returns_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """optional 工具缺失 → warn 不退出，返回空字符串."""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    result = pf.preflight_or_exit("ruff")
    assert result == ""
    captured = capsys.readouterr()
    assert "WARN" in captured.err or "warn" in captured.err.lower()


def test_tool_deps_schema_completeness() -> None:
    """每个 TOOL_DEPS 条目必须有 bin + install 三平台 + purpose."""
    for key, dep in pf.TOOL_DEPS.items():
        assert "bin" in dep, f"{key} 缺 bin"
        assert "install" in dep, f"{key} 缺 install"
        for p in ("Darwin", "Linux", "Windows"):
            assert p in dep["install"], f"{key} 缺 {p} install 命令"
        assert "purpose" in dep, f"{key} 缺 purpose"
