"""aise_scope_check.py 单元测试（v3.3 架构 T3）

验证 worker 改的文件是否都在 declared task.scope.paths 之内。
违规 → exit 1 + 列出。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
RUN_INIT = SCRIPTS / "aise_run_init.py"
SCOPE_CHECK = SCRIPTS / "aise_scope_check.py"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _init_git(cwd: Path) -> None:
    _git(cwd, "init", "-b", "main")
    _git(cwd, "config", "user.email", "test@test")
    _git(cwd, "config", "user.name", "test")
    _git(cwd, "config", "commit.gpgsign", "false")


def _make_minimal_plan(scope_paths: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "task_title": "test",
        "tasks": [
            {
                "task_id": "T-001",
                "title": "task one",
                "scope": {"paths": scope_paths},
                "test_manifest": {"pipe": "pytest-junitxml"},
            }
        ],
    }


def _setup_project(tmp_path: Path, scope_paths: list[str]) -> Path:
    """建一个完整可工作的 fixture project：git + .aise/plan.json + run_init."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _init_git(proj)
    aise_dir = proj / ".aise"
    aise_dir.mkdir()
    (aise_dir / "plan.md").write_text("# test\n", encoding="utf-8")
    (aise_dir / "plan.json").write_text(
        json.dumps(_make_minimal_plan(scope_paths)), encoding="utf-8"
    )
    # 准备初始内容并提交，给 git diff 提供基准
    (proj / "README.md").write_text("init\n", encoding="utf-8")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-m", "init")
    # 跑 run_init 生成 run_context
    r = subprocess.run(
        [sys.executable, str(RUN_INIT), "--project-root", str(proj)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return proj


def _run_scope_check(
    project_root: Path, task_id: str = "T-001", extra: list[str] | None = None
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCOPE_CHECK),
           "--project-root", str(project_root), "--task-id", task_id]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ----------------------------- 基础路径 -----------------------------


def test_scope_check_no_diff_passes(tmp_path: Path) -> None:
    """工作区干净（无修改）→ exit 0."""
    proj = _setup_project(tmp_path, ["src/**", "tests/**"])
    r = _run_scope_check(proj)
    assert r.returncode == 0, f"无修改应通过: {r.stderr}"


def test_scope_check_in_scope_change_passes(tmp_path: Path) -> None:
    """所有修改都在 scope 内 → exit 0."""
    proj = _setup_project(tmp_path, ["src/**", "tests/**"])
    (proj / "src").mkdir()
    (proj / "src" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "tests").mkdir()
    (proj / "tests" / "test_foo.py").write_text("def test_x(): pass\n", encoding="utf-8")
    r = _run_scope_check(proj)
    assert r.returncode == 0, f"in-scope 应通过: {r.stdout}\n{r.stderr}"


def test_scope_check_out_of_scope_change_fails(tmp_path: Path) -> None:
    """worker 改了 scope 外的文件 → exit 1 + 列出违规."""
    proj = _setup_project(tmp_path, ["src/**"])
    (proj / "src").mkdir()
    (proj / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "lib").mkdir()
    (proj / "lib" / "outside.py").write_text("y = 1\n", encoding="utf-8")  # 越界
    r = _run_scope_check(proj)
    assert r.returncode == 1
    assert "lib/outside.py" in r.stdout or "lib/outside.py" in r.stderr


def test_scope_check_lists_all_violations(tmp_path: Path) -> None:
    """多个越界文件应全部列出."""
    proj = _setup_project(tmp_path, ["src/**"])
    (proj / "lib").mkdir()
    (proj / "lib" / "a.py").write_text("a\n", encoding="utf-8")
    (proj / "lib" / "b.py").write_text("b\n", encoding="utf-8")
    r = _run_scope_check(proj)
    assert r.returncode == 1
    output = r.stdout + r.stderr
    assert "lib/a.py" in output
    assert "lib/b.py" in output


def test_scope_check_modified_existing_file_in_scope_passes(tmp_path: Path) -> None:
    proj = _setup_project(tmp_path, ["**.md"])
    (proj / "README.md").write_text("changed\n", encoding="utf-8")
    r = _run_scope_check(proj)
    assert r.returncode == 0, f"修改 README.md（**.md 命中）应过: {r.stderr}"


def test_scope_check_deleted_file_out_of_scope_fails(tmp_path: Path) -> None:
    """删除 scope 外的文件也算越界."""
    proj = _setup_project(tmp_path, ["src/**"])
    (proj / "README.md").unlink()  # README.md 不在 scope
    r = _run_scope_check(proj)
    assert r.returncode == 1
    assert "README.md" in r.stdout + r.stderr


# ----------------------------- task_id 切换 -----------------------------


def test_scope_check_different_task_id_uses_different_scope(tmp_path: Path) -> None:
    """plan 有两个 task，scope 不同。--task-id 切换对应 scope."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _init_git(proj)
    aise_dir = proj / ".aise"
    aise_dir.mkdir()
    (aise_dir / "plan.md").write_text("# t\n", encoding="utf-8")
    plan = {
        "schema_version": "1.0",
        "task_title": "multi",
        "tasks": [
            {"task_id": "T-001", "title": "t1",
             "scope": {"paths": ["src/**"]},
             "test_manifest": {"pipe": "pytest-junitxml"}},
            {"task_id": "T-002", "title": "t2",
             "scope": {"paths": ["lib/**"]},
             "test_manifest": {"pipe": "pytest-junitxml"}},
        ],
    }
    (aise_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (proj / "README.md").write_text("x\n", encoding="utf-8")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-m", "init")
    r = subprocess.run(
        [sys.executable, str(RUN_INIT), "--project-root", str(proj)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0

    (proj / "lib").mkdir()
    (proj / "lib" / "x.py").write_text("x\n", encoding="utf-8")

    # T-001 scope = src/** → lib/x.py 越界
    r1 = _run_scope_check(proj, task_id="T-001")
    assert r1.returncode == 1
    # T-002 scope = lib/** → 命中
    r2 = _run_scope_check(proj, task_id="T-002")
    assert r2.returncode == 0


# ----------------------------- 错误处理 -----------------------------


def test_scope_check_missing_run_context_fails(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _init_git(proj)
    r = _run_scope_check(proj)
    assert r.returncode == 2
    assert "run_context" in r.stderr or "未找到" in r.stderr


def test_scope_check_unknown_task_id_fails(tmp_path: Path) -> None:
    proj = _setup_project(tmp_path, ["src/**"])
    r = _run_scope_check(proj, task_id="T-999")
    assert r.returncode == 2
    assert "T-999" in r.stderr or "task" in r.stderr.lower()


def test_scope_check_snapshot_tampered_fails(tmp_path: Path) -> None:
    """plan.snapshot.json 被篡改 → exit 2."""
    proj = _setup_project(tmp_path, ["src/**"])
    snap = proj / ".aise" / "plan.snapshot.json"
    content = snap.read_text("utf-8")
    snap.write_text(content + "  ", encoding="utf-8")  # 末尾加空格篡改
    r = _run_scope_check(proj)
    assert r.returncode == 2
    assert "snapshot" in (r.stderr + r.stdout).lower()
