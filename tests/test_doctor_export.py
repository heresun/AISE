"""aise_doctor --export 测试（v3.6）

让用户把 doctor 报告写到文件分享给团队 / 提交 issue。
设计：
  - --export <path>：把报告写到文件
  - 默认 markdown 格式；与 --json 组合时写 JSON
  - stdout 同时输出（CLI 行为不变，便于交互式使用）
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


def _run(*args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
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


def test_doctor_export_markdown_to_file(tmp_path: Path) -> None:
    out = tmp_path / "doctor-report.md"
    r = _run("--export", str(out))
    assert r.returncode in (0, 1, 2)
    assert out.exists()
    content = out.read_text("utf-8")
    assert "AISE Doctor" in content
    assert "Python" in content  # 应含 python check


def test_doctor_export_json_to_file(tmp_path: Path) -> None:
    out = tmp_path / "doctor-report.json"
    r = _run("--json", "--export", str(out))
    assert r.returncode in (0, 1, 2)
    assert out.exists()
    data = json.loads(out.read_text("utf-8"))
    assert "checks" in data
    assert "summary" in data


def test_doctor_export_still_prints_to_stdout(tmp_path: Path) -> None:
    """--export 不应禁用 stdout 输出（让交互式 CLI 体验不变）."""
    out = tmp_path / "report.md"
    r = _run("--export", str(out))
    assert "AISE Doctor" in r.stdout, "stdout 仍应展示报告"
    assert out.exists()
    # 文件内容与 stdout 一致（去 trailing whitespace）
    assert out.read_text("utf-8").strip() == r.stdout.strip()


def test_doctor_export_creates_parent_dir(tmp_path: Path) -> None:
    """目标路径父目录不存在时自动创建."""
    out = tmp_path / "nested" / "deep" / "report.md"
    r = _run("--export", str(out))
    assert r.returncode in (0, 1, 2)
    assert out.exists()


def test_doctor_export_overwrites_existing(tmp_path: Path) -> None:
    """已存在的文件应被覆盖（不抛错）."""
    out = tmp_path / "report.md"
    out.write_text("stale content", encoding="utf-8")
    r = _run("--export", str(out))
    assert r.returncode in (0, 1, 2)
    content = out.read_text("utf-8")
    assert "stale content" not in content
    assert "AISE Doctor" in content


def test_doctor_export_with_check_versions(tmp_path: Path) -> None:
    """--export + --check-versions 应把版本章节也写入文件."""
    out = tmp_path / "report.md"
    r = _run("--check-versions", "--export", str(out))
    content = out.read_text("utf-8")
    assert "版本" in content or "version" in content.lower()
    # 至少有一个工具的版本检查行
    assert "actual" in content or "min " in content
