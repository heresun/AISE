"""aise_doctor --check-versions 测试（v3.5 P1-2）

doctor 跑工具 --version 拿版本号，与 PIPE_DEFS 中的 min_version 对比：
  - 版本 ≥ min → ok
  - 版本 < min → warn（仍能用但不推荐）
  - 解析失败 → warn（不阻塞）
  - 工具缺失 → 走原来的 pipe_tools fail 路径
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = PROJECT_ROOT / "scripts" / "aise_doctor.py"


def _run_doctor(*args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        [sys.executable, str(DOCTOR), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=60,
    )


# ----------------------------- 版本解析 helper -----------------------------


def test_parse_version_from_string_basic() -> None:
    from lib.version_check import parse_version
    assert parse_version("go version go1.22.0 darwin/arm64") == (1, 22, 0)
    assert parse_version("Apache Maven 3.9.9 (8e8579a9e76f7d015ee5ec7bfcdc97d260186937)") == (3, 9, 9)
    assert parse_version("pytest 9.0.3") == (9, 0, 3)
    assert parse_version("8.0.0") == (8, 0, 0)
    assert parse_version("v25.8.2") == (25, 8, 2)
    assert parse_version("cargo 1.83.0 (2026-04-12)") == (1, 83, 0)


def test_parse_version_two_part_padded_to_three() -> None:
    """缺 patch 段 → padding 0."""
    from lib.version_check import parse_version
    assert parse_version("foo 3.9 (release)") == (3, 9, 0)


def test_parse_version_returns_none_on_no_match() -> None:
    from lib.version_check import parse_version
    assert parse_version("no version here") is None
    assert parse_version("") is None
    assert parse_version("v") is None


def test_compare_versions() -> None:
    from lib.version_check import meets_minimum
    assert meets_minimum((1, 22, 0), (1, 21, 0)) is True
    assert meets_minimum((1, 21, 0), (1, 21, 0)) is True
    assert meets_minimum((1, 20, 99), (1, 21, 0)) is False
    assert meets_minimum((2, 0, 0), (1, 21, 0)) is True
    assert meets_minimum((3, 9, 9), (3, 6, 0)) is True


# ----------------------------- doctor 集成 -----------------------------


def test_doctor_check_versions_flag_runs() -> None:
    r = _run_doctor("--check-versions", "--json")
    assert r.returncode in (0, 1, 2)
    data = json.loads(r.stdout)
    # 应含 version_checks 字段
    assert "version_checks" in data
    assert isinstance(data["version_checks"], list)


def test_doctor_check_versions_default_off() -> None:
    """不传 --check-versions 时不跑（保持快速）."""
    r = _run_doctor("--json")
    data = json.loads(r.stdout)
    # version_checks 字段缺失或为空列表
    vc = data.get("version_checks", [])
    assert vc == [], "默认 doctor 不应跑版本检查"


def test_doctor_check_versions_lists_known_tools() -> None:
    r = _run_doctor("--check-versions", "--json")
    data = json.loads(r.stdout)
    vc = data["version_checks"]
    tool_names = {v["tool"] for v in vc}
    # 至少应含 5 pipe 主要工具 + python + git
    expected = {"python", "git", "go", "mvn", "pytest", "cargo", "node"}
    intersection = expected & tool_names
    assert len(intersection) >= 5, f"版本检查应覆盖至少 5 个工具，实际: {tool_names}"


def test_doctor_check_versions_each_has_min_and_actual() -> None:
    r = _run_doctor("--check-versions", "--json")
    data = json.loads(r.stdout)
    for vc in data["version_checks"]:
        assert "tool" in vc
        assert "status" in vc
        # status ∈ {ok, warn, fail, skip}
        assert vc["status"] in {"ok", "warn", "fail", "skip"}
        # min_version 应总有
        assert "min_version" in vc


def test_doctor_markdown_check_versions_section() -> None:
    """markdown 输出含"版本检查"章节."""
    r = _run_doctor("--check-versions")
    assert "版本" in r.stdout or "version" in r.stdout.lower()


# ----------------------------- min_version 配置 -----------------------------


def test_version_minimums_constant_exists() -> None:
    """lib.version_check 必须导出 MINIMUMS 字典."""
    from lib.version_check import MINIMUMS
    assert "go" in MINIMUMS
    assert "mvn" in MINIMUMS
    assert "pytest" in MINIMUMS
    assert "node" in MINIMUMS
    assert "cargo" in MINIMUMS


def test_version_minimums_match_compatibility_matrix() -> None:
    """版本要求应与 docs/tool-compatibility-matrix.md 一致."""
    from lib.version_check import MINIMUMS
    # 按矩阵：
    assert MINIMUMS["go"]["min"] == (1, 21, 0)
    assert MINIMUMS["mvn"]["min"] == (3, 6, 0)
    assert MINIMUMS["pytest"]["min"] == (6, 0, 0)
    assert MINIMUMS["node"]["min"] == (18, 0, 0)
    assert MINIMUMS["cargo"]["min"] == (1, 70, 0)
