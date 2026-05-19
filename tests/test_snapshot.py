"""lib/snapshot.py 直接单元测试（v3.6 补充）

snapshot 是 v3.2.5 P1-D 核心防篡改组件。原本只被 aise_verify / aise_run_init /
aise_scope_check 间接测试。补充直接单元测试覆盖 process-local cache 行为
（关键设计：长跑 gate 不应被中途篡改 snapshot 影响）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import snapshot as snap_lib


def _setup_plan_md(project_root: Path, content: str = "# test plan\n") -> None:
    aise_dir = project_root / ".aise"
    aise_dir.mkdir(parents=True, exist_ok=True)
    (aise_dir / "plan.md").write_text(content, encoding="utf-8")


def _reset_cache() -> None:
    """清 process-local 缓存，避免测试间互相影响."""
    snap_lib._SNAPSHOT_CACHE = None
    snap_lib._SNAPSHOT_CACHE_KEY = None


@pytest.fixture(autouse=True)
def reset_cache_around_each_test() -> None:
    _reset_cache()
    yield
    _reset_cache()


# ----------------------------- create_snapshot -----------------------------


def test_create_snapshot_writes_json_and_sha(tmp_path: Path) -> None:
    _setup_plan_md(tmp_path, "# my plan\n## tasks\n- T-001\n")
    snap_path, sha = snap_lib.create_snapshot(tmp_path, task_title="hello")
    assert snap_path.exists()
    assert (tmp_path / ".aise" / "plan.snapshot.sha256").exists()
    assert len(sha) == 64  # sha256 hex
    snapshot = json.loads(snap_path.read_text("utf-8"))
    assert snapshot["task_title"] == "hello"
    assert "plan_md_body" in snapshot
    assert "# my plan" in snapshot["plan_md_body"]


def test_create_snapshot_no_plan_md_raises(tmp_path: Path) -> None:
    (tmp_path / ".aise").mkdir()
    with pytest.raises(FileNotFoundError):
        snap_lib.create_snapshot(tmp_path)


def test_create_snapshot_overwrites_existing(tmp_path: Path) -> None:
    _setup_plan_md(tmp_path, "v1")
    _, sha1 = snap_lib.create_snapshot(tmp_path)
    _setup_plan_md(tmp_path, "v2 different content")
    _, sha2 = snap_lib.create_snapshot(tmp_path)
    assert sha1 != sha2, "plan.md 变化时 sha 应不同"


# ----------------------------- check_snapshot -----------------------------


def test_check_snapshot_missing_returns_specific_code(tmp_path: Path) -> None:
    ok, code, snap = snap_lib.check_snapshot(tmp_path)
    assert ok is False
    assert code == "snapshot_missing"
    assert snap is None


def test_check_snapshot_sha_missing(tmp_path: Path) -> None:
    """snapshot.json 存在但 .sha256 缺失."""
    _setup_plan_md(tmp_path)
    snap_lib.create_snapshot(tmp_path)
    (tmp_path / ".aise" / "plan.snapshot.sha256").unlink()
    _reset_cache()  # 清缓存
    ok, code, _ = snap_lib.check_snapshot(tmp_path)
    assert ok is False
    assert code == "sha_missing"


def test_check_snapshot_tampered(tmp_path: Path) -> None:
    _setup_plan_md(tmp_path)
    snap_lib.create_snapshot(tmp_path)
    # 篡改 snapshot.json
    snap_path = tmp_path / ".aise" / "plan.snapshot.json"
    snap_path.write_text(snap_path.read_text() + "  ", encoding="utf-8")
    _reset_cache()
    ok, code, _ = snap_lib.check_snapshot(tmp_path)
    assert ok is False
    assert code == "snapshot_tampered"


def test_check_snapshot_ok_returns_snapshot_dict(tmp_path: Path) -> None:
    _setup_plan_md(tmp_path, "# happy path\n")
    snap_lib.create_snapshot(tmp_path, task_title="t1")
    ok, code, snap = snap_lib.check_snapshot(tmp_path)
    assert ok is True
    assert code == "ok"
    assert snap["task_title"] == "t1"


# ----------------------------- process-local cache（v3.2.5 P1-D 核心）-----------------------------


def test_check_snapshot_uses_process_local_cache(tmp_path: Path) -> None:
    """check_snapshot 成功后，盘上 snapshot 即使被外部篡改也不影响本进程."""
    _setup_plan_md(tmp_path, "# original\n")
    snap_lib.create_snapshot(tmp_path)
    # 第一次校验 → ok，缓存到 process-local
    ok1, _, snap1 = snap_lib.check_snapshot(tmp_path)
    assert ok1 is True
    # 现在外部篡改盘上 snapshot
    snap_path = tmp_path / ".aise" / "plan.snapshot.json"
    snap_path.write_text("totally invalid json {{{", encoding="utf-8")
    # 再次校验：缓存命中 → 仍 ok（v3.2.5 P1-D 防长跑 gate 中途被篡）
    ok2, _, snap2 = snap_lib.check_snapshot(tmp_path)
    assert ok2 is True
    assert snap2 == snap1, "应返回缓存内容而非重读盘"


def test_check_snapshot_cache_keyed_by_project_root(tmp_path: Path) -> None:
    """不同 project_root 不共享缓存."""
    proj_a = tmp_path / "a"
    proj_a.mkdir()
    _setup_plan_md(proj_a, "# A\n")
    snap_lib.create_snapshot(proj_a, task_title="A")

    proj_b = tmp_path / "b"
    proj_b.mkdir()
    _setup_plan_md(proj_b, "# B\n")
    snap_lib.create_snapshot(proj_b, task_title="B")

    _, _, snap_a = snap_lib.check_snapshot(proj_a)
    _, _, snap_b = snap_lib.check_snapshot(proj_b)
    assert snap_a["task_title"] == "A"
    assert snap_b["task_title"] == "B"


# ----------------------------- require_snapshot helper -----------------------------


def test_require_snapshot_exits_on_failure(tmp_path: Path) -> None:
    """require_snapshot 在失败时 sys.exit(2)，成功返回 dict."""
    with pytest.raises(SystemExit) as exc_info:
        snap_lib.require_snapshot(tmp_path, gate_name="testgate")
    assert exc_info.value.code == 2


def test_require_snapshot_success_returns_dict(tmp_path: Path) -> None:
    _setup_plan_md(tmp_path, "# x\n")
    snap_lib.create_snapshot(tmp_path, task_title="x")
    snap = snap_lib.require_snapshot(tmp_path, gate_name="testgate")
    assert snap["task_title"] == "x"
