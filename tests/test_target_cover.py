"""target_covers 单元测试（v3.2.5 §12.3 救命路径）

Spike-1 仅覆盖：
  - 同 kind 同 id 完全匹配 → covers
  - cross-kind: actual.kind=testcase + declared.kind=package
    且 actual.parent_package == declared.id → covers
  - 其他 cross-kind 组合 → False（Spike-2 扩展）
"""
from __future__ import annotations

import pytest

from lib.target_cover import target_covers


# ----------------------------- same-kind exact -----------------------------


def test_same_kind_same_id_covers() -> None:
    actual = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is True


def test_same_kind_different_id_does_not_cover() -> None:
    actual = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/admin"}
    assert target_covers(actual, declared) is False


# ----------------------------- cross-kind testcase → package -----------------------------


def test_testcase_covers_package_when_parent_package_matches() -> None:
    actual = {
        "kind": "testcase",
        "id": "TestLogin",
        "parent_package": "github.com/foo/bar/pkg/user",
        "parent_class": "user.ServiceTest",
        "parent_file": "pkg/user/service_test.go",
    }
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is True


def test_testcase_does_not_cover_unrelated_package() -> None:
    actual = {
        "kind": "testcase",
        "id": "TestLogin",
        "parent_package": "github.com/foo/bar/pkg/admin",
    }
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is False


def test_testcase_missing_parent_package_does_not_cover() -> None:
    actual = {"kind": "testcase", "id": "TestLogin"}
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is False


def test_testcase_empty_parent_package_does_not_cover() -> None:
    actual = {"kind": "testcase", "id": "TestLogin", "parent_package": ""}
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is False


# ----------------------------- unsupported cross-kind -----------------------------


def test_testcase_to_file_not_supported_yet_returns_false() -> None:
    """Spike-1 仅实现 testcase→package；其他 cross-kind 路径返回 False。"""
    actual = {
        "kind": "testcase",
        "id": "TestLogin",
        "parent_file": "pkg/user/service_test.go",
    }
    declared = {"kind": "file", "id": "pkg/user/service_test.go"}
    assert target_covers(actual, declared) is False


def test_file_to_package_not_supported_yet_returns_false() -> None:
    actual = {"kind": "file", "id": "pkg/user/service_test.go"}
    declared = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    assert target_covers(actual, declared) is False


def test_package_to_testcase_not_supported_returns_false() -> None:
    actual = {"kind": "package", "id": "github.com/foo/bar/pkg/user"}
    declared = {"kind": "testcase", "id": "TestLogin"}
    assert target_covers(actual, declared) is False


# ----------------------------- malformed input -----------------------------


def test_missing_kind_returns_false() -> None:
    assert target_covers({}, {"kind": "package", "id": "x"}) is False
    assert target_covers({"kind": "testcase", "id": "x"}, {}) is False


def test_none_input_returns_false() -> None:
    assert target_covers(None, {"kind": "package", "id": "x"}) is False  # type: ignore[arg-type]
    assert target_covers({"kind": "testcase", "id": "x"}, None) is False  # type: ignore[arg-type]


# ----------------------------- 集合层 helper -----------------------------


def test_any_covers_all_declared() -> None:
    """常用形态：actuals 是否覆盖所有 declared targets"""
    from lib.target_cover import all_declared_covered

    actuals = [
        {"kind": "testcase", "id": "TestA", "parent_package": "pkg/user"},
        {"kind": "testcase", "id": "TestB", "parent_package": "pkg/admin"},
    ]
    declared = [
        {"kind": "package", "id": "pkg/user"},
        {"kind": "package", "id": "pkg/admin"},
    ]
    ok, missing = all_declared_covered(actuals, declared)
    assert ok is True
    assert missing == []


def test_any_covers_reports_missing_declared() -> None:
    from lib.target_cover import all_declared_covered

    actuals = [{"kind": "testcase", "id": "TestA", "parent_package": "pkg/user"}]
    declared = [
        {"kind": "package", "id": "pkg/user"},
        {"kind": "package", "id": "pkg/admin"},  # 无 actual 命中
    ]
    ok, missing = all_declared_covered(actuals, declared)
    assert ok is False
    assert len(missing) == 1
    assert missing[0]["id"] == "pkg/admin"
