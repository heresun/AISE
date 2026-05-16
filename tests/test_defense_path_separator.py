"""defense_in_depth_check 路径分隔符跨平台归一测试（v3.3 P0-2）

Windows 上 target 可能用 `\\` 分隔（如 `.\\pkg\\foo`），allowed_patterns
通常用 `/`（如 `./pkg/**`）。defense_in_depth_check 必须归一后再匹配，
否则 Windows 用户的所有合法 target 都会被拦截。
"""
from __future__ import annotations

import pytest

from lib import event_runner as er


# ----------------------------- 反斜杠 target 归一 -----------------------------


def test_windows_backslash_target_matches_forward_slash_pattern() -> None:
    """Windows `.\\pkg\\foo` 应能匹配 allowed `./pkg/**`."""
    ok, info = er.defense_in_depth_check([".\\pkg\\foo"], ["./pkg/**"])
    assert ok is True, f"反斜杠 target 应归一后匹配: {info}"


def test_windows_backslash_pattern_also_normalized() -> None:
    """allowed_patterns 也允许写反斜杠（不推荐但兼容）."""
    ok, _ = er.defense_in_depth_check(["./pkg/foo"], [".\\pkg\\**"])
    assert ok is True


def test_mixed_separators_in_one_target() -> None:
    """混合分隔符 `.\\pkg/foo` 也应被归一."""
    ok, _ = er.defense_in_depth_check([".\\pkg/foo\\bar"], ["./pkg/**"])
    assert ok is True


def test_forward_slash_unchanged() -> None:
    """纯正斜杠路径（Unix）行为不变."""
    ok, _ = er.defense_in_depth_check(["./pkg/user"], ["./pkg/**"])
    assert ok is True


def test_drive_letter_windows_path() -> None:
    """Windows 绝对路径 `C:\\Users\\...` 与 `C:/Users/...` 归一一致."""
    ok1, _ = er.defense_in_depth_check(["C:\\Users\\foo\\pkg\\bar"], ["C:/Users/**"])
    ok2, _ = er.defense_in_depth_check(["C:/Users/foo/pkg/bar"], ["C:/Users/**"])
    assert ok1 is True
    assert ok2 is True


def test_backslash_does_not_bypass_block() -> None:
    """归一不应让恶意 target 绕过白名单：`..\\..\\etc\\passwd` 仍应被拦截."""
    ok, info = er.defense_in_depth_check(
        ["..\\..\\etc\\passwd"], ["./pkg/**"]
    )
    assert ok is False
    assert info["code"] == "pipe_target_breached_manifest"


def test_normalize_helper_exposed() -> None:
    """_normalize_path 是公开 helper（v3.3 设计：归一逻辑可复用 + 测试可见）."""
    assert er._normalize_path(".\\pkg\\foo") == "./pkg/foo"
    assert er._normalize_path("./pkg/foo") == "./pkg/foo"
    assert er._normalize_path("C:\\a\\b") == "C:/a/b"
    assert er._normalize_path("") == ""
