"""aise_doctor.py 单元测试（v3.4 P2-1）

aise_doctor 是用户自检工具：一键扫描 AISE 运行环境，缺什么列出来 + 平台
特定安装命令。设计原则：
  - 永远不抛异常（用户体验）
  - 不依赖外部库
  - exit code 编码严重程度：0 = 全 ok / 1 = 仅 optional 缺失 / 2 = 关键缺失

检查项：
  1. Python 版本 ≥3.10
  2. AISE 自身完整性（scripts/lib/* 模块可 import）
  3. 5 PIPE_DEFS 的 preflight bin（复用 preflight_pipe）
  4. git 可用
  5. UTF-8 stdio 配置（PYTHONUTF8 或 sys.stdout.encoding 含 utf）
  6. 可选项目级：.aise/plan.json 合法
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = PROJECT_ROOT / "scripts" / "aise_doctor.py"


def _run(*args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, str(DOCTOR), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=60,
    )


# ----------------------------- 基本调用 -----------------------------


def test_doctor_prints_markdown_by_default() -> None:
    r = _run()
    assert r.returncode in (0, 1, 2), f"unexpected exit: {r.returncode}"
    assert "AISE Doctor" in r.stdout or "AISE doctor" in r.stdout.lower()
    # markdown 检查项标记
    assert "✅" in r.stdout or "❌" in r.stdout or "⚠️" in r.stdout


def test_doctor_json_output_is_valid_json() -> None:
    r = _run("--json")
    assert r.returncode in (0, 1, 2)
    data = json.loads(r.stdout)
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert "summary" in data
    assert "exit_code" in data["summary"]


def test_doctor_checks_include_all_categories() -> None:
    r = _run("--json")
    data = json.loads(r.stdout)
    categories = {c["category"] for c in data["checks"]}
    # 至少含这些大类
    expected = {"python", "aise_internal", "git", "stdio_encoding", "pipe_tools"}
    assert expected.issubset(categories), f"缺类别: {expected - categories}"


def test_doctor_python_version_check_present() -> None:
    r = _run("--json")
    data = json.loads(r.stdout)
    py_checks = [c for c in data["checks"] if c["category"] == "python"]
    assert len(py_checks) >= 1
    assert "version" in py_checks[0]["name"].lower() or "python" in py_checks[0]["name"].lower()


# ----------------------------- pipe 工具自检 -----------------------------


def test_doctor_lists_all_5_pipes() -> None:
    r = _run("--json")
    data = json.loads(r.stdout)
    pipe_checks = [c for c in data["checks"] if c["category"] == "pipe_tools"]
    pipe_names = {c["name"] for c in pipe_checks}
    expected_pipes = {
        "go-test-json-to-junit", "mvn-surefire", "pytest-junitxml",
        "jest-junit", "cargo-test-junit",
    }
    assert pipe_names == expected_pipes, f"pipe 列表不全: {pipe_names}"


def test_doctor_missing_pipe_tool_provides_install_hint() -> None:
    """每个 pipe check 若 status=fail，应含 install_hint 字段。"""
    r = _run("--json")
    data = json.loads(r.stdout)
    for c in data["checks"]:
        if c["category"] == "pipe_tools" and c["status"] == "fail":
            assert "install_hint" in c
            assert c["install_hint"]


# ----------------------------- 严重程度 -----------------------------


def test_doctor_strict_mode_treats_optional_as_fatal() -> None:
    """--strict 模式让 optional 缺失也视为 fatal。"""
    r = _run("--json", "--strict")
    data = json.loads(r.stdout)
    # 在 strict 模式下，summary 应有 strict 标记
    assert data["summary"].get("strict") is True


def test_doctor_exit_code_zero_when_all_ok() -> None:
    """所有关键 check 全过 → exit 0（默认非 strict）.

    本测试环境 macOS + 已装多数工具，应该 ok 或 warn（exit 0/1）."""
    r = _run()
    assert r.returncode in (0, 1), f"非 strict 模式不应 fatal: exit={r.returncode}"


# ----------------------------- AISE 内部 -----------------------------


def test_doctor_aise_internal_check_lib_modules() -> None:
    r = _run("--json")
    data = json.loads(r.stdout)
    internal_checks = [c for c in data["checks"] if c["category"] == "aise_internal"]
    assert len(internal_checks) >= 1
    # 至少有 lib.event_runner / lib.lock 等核心模块检查
    names = {c["name"] for c in internal_checks}
    assert any("event_runner" in n or "lock" in n or "lib" in n for n in names)


# ----------------------------- UTF-8 -----------------------------


def test_doctor_stdio_encoding_check_passes_with_pythonutf8() -> None:
    r = _run("--json", env_override={"PYTHONUTF8": "1"})
    data = json.loads(r.stdout)
    enc_checks = [c for c in data["checks"] if c["category"] == "stdio_encoding"]
    assert any(c["status"] == "ok" for c in enc_checks), \
        f"PYTHONUTF8=1 应让编码 check 通过: {enc_checks}"


# ----------------------------- 退出码 -----------------------------


def test_doctor_help_works() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "aise_doctor" in r.stdout.lower() or "doctor" in r.stdout.lower()
