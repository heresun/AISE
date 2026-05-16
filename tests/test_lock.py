"""scripts/lib/lock.py 单元测试（v3.2.5 §4.4.6 验收）

覆盖：
  - mkdir 原子性 acquire 成功
  - EEXIST 重试到 release 后获取
  - lock_timeout（超时仍 EEXIST）
  - release_lock 幂等清理
  - holder.json 含 pid + acquired_at（ISO 8601）
  - stale 检测：holder.pid 已死 + 超 stale_threshold_ms → 强制清理重试
  - stale 检测：holder.pid 仍活 → 排队不清理
  - threshold 未到 → 不清理
  - holder.json 缺失但超 threshold → 视为 stale
  - 并发抢锁：两个进程同时 acquire，只有一个 ok=True
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import sys
import time
from pathlib import Path

import pytest

from lib import lock as lock_lib


ISO_8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


# ----------------------------- 基础功能 -----------------------------


def test_acquire_lock_success(tmp_path: Path) -> None:
    lock_dir = tmp_path / "iteration.lock"
    result = lock_lib.acquire_lock(lock_dir, timeout_ms=1000, retry_interval_ms=10)
    try:
        assert result["ok"] is True
        assert Path(result["lock_dir"]) == lock_dir
        assert lock_dir.is_dir()
        holder = json.loads((lock_dir / "holder.json").read_text("utf-8"))
        assert holder["pid"] == os.getpid()
        assert isinstance(holder["pid"], int)
        assert ISO_8601_RE.match(holder["acquired_at"]) is not None
    finally:
        lock_lib.release_lock(result)


def test_release_lock_cleans_dir(tmp_path: Path) -> None:
    lock_dir = tmp_path / "iter.lock"
    result = lock_lib.acquire_lock(lock_dir, timeout_ms=500, retry_interval_ms=10)
    assert result["ok"] is True
    assert lock_dir.exists()
    lock_lib.release_lock(result)
    assert not lock_dir.exists()


def test_release_lock_idempotent(tmp_path: Path) -> None:
    """release 失败结果时不报错，重复 release 已清理目录也不报错"""
    failed = {"ok": False, "code": "lock_timeout"}
    lock_lib.release_lock(failed)  # 不应抛
    lock_dir = tmp_path / "iter.lock"
    result = lock_lib.acquire_lock(lock_dir, timeout_ms=500, retry_interval_ms=10)
    lock_lib.release_lock(result)
    lock_lib.release_lock(result)  # 重复 release 不抛


def test_acquire_lock_timeout_when_held(tmp_path: Path) -> None:
    lock_dir = tmp_path / "iter.lock"
    holder = lock_lib.acquire_lock(lock_dir, timeout_ms=200, retry_interval_ms=10)
    try:
        t0 = time.time()
        second = lock_lib.acquire_lock(
            lock_dir,
            timeout_ms=150,
            retry_interval_ms=20,
            stale_threshold_ms=10_000_000,  # 禁用 stale 清理
        )
        elapsed = time.time() - t0
        assert second["ok"] is False
        assert second["code"] == "lock_timeout"
        assert second["timeout_ms"] == 150
        assert 0.1 <= elapsed < 1.0, f"超时窗口异常: {elapsed}"
    finally:
        lock_lib.release_lock(holder)


def test_acquire_lock_succeeds_after_release(tmp_path: Path) -> None:
    lock_dir = tmp_path / "iter.lock"
    first = lock_lib.acquire_lock(lock_dir, timeout_ms=500, retry_interval_ms=10)
    assert first["ok"] is True
    lock_lib.release_lock(first)
    second = lock_lib.acquire_lock(lock_dir, timeout_ms=500, retry_interval_ms=10)
    try:
        assert second["ok"] is True
    finally:
        lock_lib.release_lock(second)


# ----------------------------- Stale 检测 -----------------------------


def test_stale_lock_with_dead_pid_is_force_cleaned(tmp_path: Path) -> None:
    """holder.pid 已死 + 超 stale_threshold → 强制清理重试，acquire 成功"""
    lock_dir = tmp_path / "iter.lock"
    lock_dir.mkdir()
    dead_pid = 999_999_999  # 系统 PID 上限通常 < 4 亿
    (lock_dir / "holder.json").write_text(
        json.dumps({"pid": dead_pid, "acquired_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    result = lock_lib.acquire_lock(
        lock_dir,
        timeout_ms=1000,
        retry_interval_ms=20,
        stale_threshold_ms=1,
    )
    try:
        assert result["ok"] is True, f"应强制清理 stale 锁: {result}"
        holder = json.loads((lock_dir / "holder.json").read_text("utf-8"))
        assert holder["pid"] == os.getpid()
    finally:
        lock_lib.release_lock(result)


def test_stale_lock_with_live_pid_not_cleaned(tmp_path: Path) -> None:
    """holder.pid 仍活 → 不强制清理，排队 timeout"""
    lock_dir = tmp_path / "iter.lock"
    lock_dir.mkdir()
    (lock_dir / "holder.json").write_text(
        json.dumps({"pid": os.getpid(), "acquired_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    result = lock_lib.acquire_lock(
        lock_dir,
        timeout_ms=150,
        retry_interval_ms=20,
        stale_threshold_ms=1,
    )
    assert result["ok"] is False
    assert result["code"] == "lock_timeout"


def test_stale_threshold_not_reached_keeps_lock(tmp_path: Path) -> None:
    """threshold 未到 → 即使 pid 死了也不清理"""
    lock_dir = tmp_path / "iter.lock"
    lock_dir.mkdir()
    dead_pid = 999_999_999
    now_iso = lock_lib._now_iso()
    (lock_dir / "holder.json").write_text(
        json.dumps({"pid": dead_pid, "acquired_at": now_iso}),
        encoding="utf-8",
    )

    result = lock_lib.acquire_lock(
        lock_dir,
        timeout_ms=120,
        retry_interval_ms=20,
        stale_threshold_ms=600_000,
    )
    assert result["ok"] is False
    assert result["code"] == "lock_timeout"


def test_stale_lock_missing_holder_json_is_stale_after_threshold(tmp_path: Path) -> None:
    """lock_dir 存在但 holder.json 缺失 → 超 threshold 视为 stale"""
    lock_dir = tmp_path / "iter.lock"
    lock_dir.mkdir()
    time.sleep(0.05)
    result = lock_lib.acquire_lock(
        lock_dir,
        timeout_ms=500,
        retry_interval_ms=20,
        stale_threshold_ms=1,
    )
    try:
        assert result["ok"] is True
    finally:
        lock_lib.release_lock(result)


# ----------------------------- 并发抢锁 -----------------------------


def _worker_try_acquire(
    scripts_dir: str,
    lock_dir_str: str,
    timeout_ms: int,
    hold_sec: float,
    queue: mp.Queue,
) -> None:
    sys.path.insert(0, scripts_dir)
    from lib import lock as _lock_lib  # type: ignore
    res = _lock_lib.acquire_lock(
        Path(lock_dir_str),
        timeout_ms=timeout_ms,
        retry_interval_ms=10,
        stale_threshold_ms=10_000_000,
    )
    queue.put(res["ok"])
    if res["ok"]:
        time.sleep(hold_sec)
        _lock_lib.release_lock(res)


def test_concurrent_acquire_only_one_wins(tmp_path: Path) -> None:
    """瞬时并发：第一个持锁 800ms，第二个 timeout 200ms → 第二个必失败。

    验证 mkdir 原子性在并发下保证"同一时刻只有一个 acquire 成功"。
    """
    lock_dir = tmp_path / "iter.lock"
    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    p1 = ctx.Process(
        target=_worker_try_acquire,
        args=(scripts_dir, str(lock_dir), 500, 0.8, q),
    )
    p2 = ctx.Process(
        target=_worker_try_acquire,
        args=(scripts_dir, str(lock_dir), 200, 0.0, q),
    )
    p1.start()
    # 让 p1 略微先 acquire，模拟"先到先得"
    time.sleep(0.05)
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    results = [q.get(timeout=1), q.get(timeout=1)]
    assert sorted(results) == [False, True], f"并发抢锁未串行: {results}"
