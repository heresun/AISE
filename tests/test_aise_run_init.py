"""aise_run_init.py 单元测试（v3.3 架构补完 T2）

覆盖 docs/plan-schema.md 全部校验项：
  - 顶级：schema_version / task_title / tasks 非空
  - 每个 task：task_id 必填唯一 / scope.paths 非空 / pipe 在 PIPE_DEFS
  - dependencies：拓扑可解 + 引用存在 task
  - shared_evidence_tasks：scope 交集 sanity
  - 成功路径：分配 run_id + 创建 .aise/runs/<run_id>/run_context.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
RUN_INIT = SCRIPTS / "aise_run_init.py"


def _write_plan(project_root: Path, plan: dict) -> Path:
    aise_dir = project_root / ".aise"
    aise_dir.mkdir(parents=True, exist_ok=True)
    # plan.md 兼容存在（snapshot 需要）
    (aise_dir / "plan.md").write_text(
        f"# {plan.get('task_title', 'test')}\n", encoding="utf-8"
    )
    plan_json = aise_dir / "plan.json"
    plan_json.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_json


def _run(project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUN_INIT), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _minimal_valid_plan() -> dict:
    return {
        "schema_version": "1.0",
        "task_title": "test",
        "tasks": [
            {
                "task_id": "T-001",
                "title": "task one",
                "scope": {"paths": ["src/**", "tests/**"]},
                "test_manifest": {"pipe": "pytest-junitxml"},
            }
        ],
    }


# ----------------------------- 顶级 schema -----------------------------


def test_run_init_succeeds_on_minimal_valid_plan(tmp_path: Path) -> None:
    _write_plan(tmp_path, _minimal_valid_plan())
    proc = _run(tmp_path)
    assert proc.returncode == 0, f"valid plan 应通过: stderr={proc.stderr}"
    runs_dir = tmp_path / ".aise" / "runs"
    assert runs_dir.exists()
    run_dirs = list(runs_dir.iterdir())
    assert len(run_dirs) == 1
    ctx_path = run_dirs[0] / "run_context.json"
    assert ctx_path.exists()
    ctx = json.loads(ctx_path.read_text("utf-8"))
    assert ctx["schema_version"] == "1.0"
    assert ctx["run_id"] == run_dirs[0].name
    assert "plan_snapshot" in ctx
    assert ctx["scope_policy"]["mtime_window_tolerance_ms"] == 2000


def test_run_init_missing_schema_version_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    del p["schema_version"]
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "schema_version" in proc.stderr


def test_run_init_unsupported_schema_version_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["schema_version"] = "0.9"
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "schema_version" in proc.stderr


def test_run_init_empty_task_title_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["task_title"] = ""
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2


def test_run_init_empty_tasks_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"] = []
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "tasks" in proc.stderr


def test_run_init_missing_plan_json_fails(tmp_path: Path) -> None:
    (tmp_path / ".aise").mkdir()
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "plan.json" in proc.stderr


def test_run_init_invalid_json_fails(tmp_path: Path) -> None:
    (tmp_path / ".aise").mkdir()
    (tmp_path / ".aise" / "plan.json").write_text("{not valid json", encoding="utf-8")
    proc = _run(tmp_path)
    assert proc.returncode == 2


# ----------------------------- task 级别校验 -----------------------------


def test_run_init_missing_task_id_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    del p["tasks"][0]["task_id"]
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "task_id" in proc.stderr


def test_run_init_duplicate_task_id_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"].append({
        "task_id": "T-001",  # 重复
        "title": "dup",
        "scope": {"paths": ["x/**"]},
        "test_manifest": {"pipe": "pytest-junitxml"},
    })
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "duplicate" in proc.stderr.lower() or "重复" in proc.stderr


def test_run_init_empty_scope_paths_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"][0]["scope"]["paths"] = []
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "scope" in proc.stderr or "paths" in proc.stderr


def test_run_init_unknown_pipe_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"][0]["test_manifest"]["pipe"] = "fake-runner"
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "pipe" in proc.stderr


# ----------------------------- dependencies -----------------------------


def test_run_init_unknown_dependency_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"][0]["dependencies"] = ["T-999"]
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "T-999" in proc.stderr or "dependency" in proc.stderr.lower()


def test_run_init_dependency_cycle_fails(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"][0]["dependencies"] = ["T-002"]
    p["tasks"].append({
        "task_id": "T-002",
        "title": "t2",
        "scope": {"paths": ["src/**"]},
        "test_manifest": {"pipe": "pytest-junitxml"},
        "dependencies": ["T-001"],  # 环
    })
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "cycle" in proc.stderr.lower() or "环" in proc.stderr


# ----------------------------- shared_evidence_tasks disjoint -----------------------------


def test_run_init_shared_evidence_disjoint_scope_fails(tmp_path: Path) -> None:
    """v3.2.5 P1-C：shared_evidence scope 与本 scope 完全不相交 → 拒绝."""
    p = _minimal_valid_plan()
    p["tasks"][0]["scope"]["paths"] = ["src/auth/**"]
    p["tasks"][0]["shared_evidence_tasks"] = ["T-002"]
    p["tasks"].append({
        "task_id": "T-002",
        "title": "无关 task",
        "scope": {"paths": ["src/billing/**"]},  # 与 T-001 scope 完全不相交
        "test_manifest": {"pipe": "pytest-junitxml"},
    })
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 2
    assert "disjoint" in proc.stderr.lower() or "shared_evidence" in proc.stderr


def test_run_init_shared_evidence_disjoint_allowed_by_flag(tmp_path: Path) -> None:
    """allow_disjoint_shared_evidence: true 顶级标志 → 降级为 warn，仍 pass."""
    p = _minimal_valid_plan()
    p["allow_disjoint_shared_evidence"] = True
    p["tasks"][0]["scope"]["paths"] = ["src/auth/**"]
    p["tasks"][0]["shared_evidence_tasks"] = ["T-002"]
    p["tasks"].append({
        "task_id": "T-002",
        "title": "无关",
        "scope": {"paths": ["src/billing/**"]},
        "test_manifest": {"pipe": "pytest-junitxml"},
    })
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 0, f"flag 允许时应通过: {proc.stderr}"


# ----------------------------- run_id 格式 -----------------------------


def test_run_init_run_id_format(tmp_path: Path) -> None:
    _write_plan(tmp_path, _minimal_valid_plan())
    proc = _run(tmp_path)
    assert proc.returncode == 0
    run_dirs = list((tmp_path / ".aise" / "runs").iterdir())
    rid = run_dirs[0].name
    # 格式：YYYYMMDD-HHMMSS-<6 hex>
    assert re.match(r"^\d{8}-\d{6}-[0-9a-f]{6}$", rid), f"run_id 格式不对: {rid}"


def test_run_init_creates_snapshot(tmp_path: Path) -> None:
    """成功后 plan.snapshot.json + .sha256 应生成."""
    _write_plan(tmp_path, _minimal_valid_plan())
    proc = _run(tmp_path)
    assert proc.returncode == 0
    aise_dir = tmp_path / ".aise"
    assert (aise_dir / "plan.snapshot.json").exists()
    assert (aise_dir / "plan.snapshot.sha256").exists()


def test_run_init_run_context_includes_normalized_tasks(tmp_path: Path) -> None:
    p = _minimal_valid_plan()
    p["tasks"][0]["scope"]["paths"] = ["src/calc/**", "tests/**"]
    _write_plan(tmp_path, p)
    proc = _run(tmp_path)
    assert proc.returncode == 0
    ctx_path = next((tmp_path / ".aise" / "runs").iterdir()) / "run_context.json"
    ctx = json.loads(ctx_path.read_text("utf-8"))
    assert ctx["tasks"][0]["task_id"] == "T-001"
    assert "src/calc/**" in ctx["tasks"][0]["scope"]["paths"]
