"""lib/lock.py 在 Windows 上的 pid 探测专项测试（v3.3 P0-3）

问题：Windows 上 os.kill(pid, 0) 实际是 OpenProcess + GetExitCodeProcess，
对"进程已退出但 handle 未释放"的场景会**误判存活**——这会让 stale 锁
永远清不掉，AISE gate 长时间卡死。

修复：Windows 平台显式 ctypes 调 OpenProcess + GetExitCodeProcess + 比对
STILL_ACTIVE (259)。

本测试用 monkeypatch 验证 platform.system 路由：
  - Darwin / Linux → 走 POSIX 路径（os.kill signal 0）
  - Windows → 走 _check_pid_alive_windows()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from lib import lock as lock_lib


# ----------------------------- 平台路由 -----------------------------


def test_posix_uses_os_kill_signal_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Darwin / Linux 走 os.kill(pid, 0) 路径."""
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def fake_kill(pid, sig):
        calls.append((pid, sig))
        # 模拟成功（进程活）
        return None

    monkeypatch.setattr(os, "kill", fake_kill)
    result = lock_lib._check_pid_alive(os.getpid())
    assert result is True
    assert calls == [(os.getpid(), 0)]


def test_windows_routes_to_specific_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.platform == 'win32' → 调 _check_pid_alive_windows()，
    不走 os.kill 路径。"""
    monkeypatch.setattr(sys, "platform", "win32")
    calls = {"windows": 0, "posix_kill": 0}

    def fake_windows(pid):
        calls["windows"] += 1
        return True

    def fake_kill(pid, sig):
        calls["posix_kill"] += 1
        return None

    monkeypatch.setattr(lock_lib, "_check_pid_alive_windows", fake_windows)
    monkeypatch.setattr(os, "kill", fake_kill)
    result = lock_lib._check_pid_alive(12345)
    assert result is True
    assert calls["windows"] == 1
    assert calls["posix_kill"] == 0


def test_windows_helper_exists_and_callable() -> None:
    """_check_pid_alive_windows 必须存在并可调用，即使在 mac 上跑测试也不抛
    NameError（mac 上调用走 mock，但函数本身要能 import）。"""
    assert hasattr(lock_lib, "_check_pid_alive_windows")
    assert callable(lock_lib._check_pid_alive_windows)


# ----------------------------- 不存活 pid -----------------------------


def test_zero_or_negative_pid_returns_false() -> None:
    assert lock_lib._check_pid_alive(0) is False
    assert lock_lib._check_pid_alive(-1) is False


def test_huge_pid_returns_false() -> None:
    """999_999_999 远大于系统 PID 上限，应返回 False."""
    assert lock_lib._check_pid_alive(999_999_999) is False


# ----------------------------- Windows STILL_ACTIVE 常量 -----------------------------


def test_still_active_constant_is_259() -> None:
    """Windows STILL_ACTIVE = 259（GetExitCodeProcess 返回值）。"""
    assert lock_lib.STILL_ACTIVE == 259


# ----------------------------- 集成：stale 检测在 Windows 不会被假阳性卡死 -----------------------------


def test_stale_lock_with_windows_dead_pid_still_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟 Windows 平台 + 假装 pid 已死 → acquire_lock 应强制清理 stale 锁."""
    import json

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(lock_lib, "_check_pid_alive_windows", lambda pid: False)

    lock_dir = tmp_path / "iter.lock"
    lock_dir.mkdir()
    (lock_dir / "holder.json").write_text(
        json.dumps({"pid": 999_999_999, "acquired_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    result = lock_lib.acquire_lock(
        lock_dir,
        timeout_ms=500,
        retry_interval_ms=20,
        stale_threshold_ms=1,
    )
    try:
        assert result["ok"] is True, "Windows pid 死 + 超 threshold → 应清"
    finally:
        lock_lib.release_lock(result)
