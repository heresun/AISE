"""跨平台 iteration 锁（v3.2.5 §4.4.6）

设计要点：
  - 统一走 mkdir 原子性（POSIX 与 Windows NTFS 都是原子操作）
  - 不依赖 fcntl / flock / proper-lockfile，纯标准库
  - 持有者信息写入 holder.json（pid + acquired_at），便于诊断
  - Stale 检测：holder.pid 已死 + acquired_at 超 stale_threshold_ms → 强制清理重试
  - holder.json 缺失且 lock_dir 已超 threshold 也视为 stale

并发约束：AISE 默认 single-worker-per-task 串行，本锁仅保护 iteration 号分配。
不支持读锁/写锁分离。

接口：
  acquire_lock(lock_dir, timeout_ms=5000, retry_interval_ms=50, stale_threshold_ms=600000)
    → {"ok": True, "lock_dir": Path}                  成功
    → {"ok": False, "code": "lock_timeout", "timeout_ms": ...}
    → {"ok": False, "code": "lock_acquire_failed", "err": "..."}
  release_lock(result)  幂等
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

PathLike = Union[str, Path]

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_RETRY_INTERVAL_MS = 50
DEFAULT_STALE_THRESHOLD_MS = 600_000  # 10 分钟


def _now_iso() -> str:
    """UTC ISO-8601 with millisecond precision and Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_iso_ms(iso: str) -> int:
    """解析 ISO-8601 → epoch ms。失败返回 0（视为非常古老）。"""
    if not iso:
        return 0
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _check_pid_alive(pid: int) -> bool:
    """探测 pid 是否仍存活。跨平台。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 仅探测，不发信号
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但属于其他用户 → 仍认为活
        return True
    except OSError:
        return False
    return True


def _read_holder(lock_dir: Path) -> Dict[str, Any]:
    """读 holder.json，缺失或损坏返回空 dict。"""
    holder_path = lock_dir / "holder.json"
    try:
        return json.loads(holder_path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _is_stale(lock_dir: Path, stale_threshold_ms: int) -> bool:
    """判定锁是否 stale。逻辑：
      1. 读 holder.json
      2. 若有 pid 且仍活 → 不 stale
      3. 否则若 acquired_at 已超 threshold → stale
      4. holder.json 缺失：用 lock_dir 自身 mtime 与 threshold 比较
    """
    holder = _read_holder(lock_dir)
    now_ms = _now_ms()

    if holder:
        pid = holder.get("pid")
        if isinstance(pid, int) and _check_pid_alive(pid):
            return False  # pid 活着，绝不清
        acquired_ms = _parse_iso_ms(holder.get("acquired_at", ""))
        if acquired_ms <= 0:
            # acquired_at 解析失败，回退 lock_dir mtime
            try:
                acquired_ms = int(lock_dir.stat().st_mtime * 1000)
            except OSError:
                return False
        return (now_ms - acquired_ms) > stale_threshold_ms

    # holder.json 缺失：用 lock_dir 自身 mtime
    try:
        dir_mtime_ms = int(lock_dir.stat().st_mtime * 1000)
    except OSError:
        return False
    return (now_ms - dir_mtime_ms) > stale_threshold_ms


def _force_clean(lock_dir: Path) -> None:
    """强制移除 stale 锁目录。静默忽略错误（下次 acquire 会再试）。"""
    try:
        shutil.rmtree(lock_dir, ignore_errors=True)
    except OSError:
        pass


def _write_holder(lock_dir: Path) -> None:
    holder = {
        "pid": os.getpid(),
        "acquired_at": _now_iso(),
    }
    (lock_dir / "holder.json").write_text(
        json.dumps(holder, ensure_ascii=False),
        encoding="utf-8",
    )


def acquire_lock(
    lock_dir: PathLike,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    retry_interval_ms: int = DEFAULT_RETRY_INTERVAL_MS,
    stale_threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS,
) -> Dict[str, Any]:
    """阻塞 acquire，最多等待 timeout_ms。

    返回 dict（永不抛异常给调用方）：
      成功：{"ok": True, "lock_dir": Path}
      超时：{"ok": False, "code": "lock_timeout", "timeout_ms": int}
      其他：{"ok": False, "code": "lock_acquire_failed", "err": str}
    """
    lock_path = Path(lock_dir)
    # 确保父目录存在
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "code": "lock_acquire_failed", "err": str(e)}

    deadline_ms = _now_ms() + max(0, timeout_ms)
    retry_sec = max(0.001, retry_interval_ms / 1000.0)

    while True:
        try:
            lock_path.mkdir(parents=False, exist_ok=False)  # 原子操作
            _write_holder(lock_path)
            return {"ok": True, "lock_dir": lock_path}
        except FileExistsError:
            # 锁被占用，先看是否 stale
            if _is_stale(lock_path, stale_threshold_ms):
                _force_clean(lock_path)
                # 不消耗 retry interval，立即重试
                continue
            # 非 stale，排队等待
            if _now_ms() >= deadline_ms:
                return {
                    "ok": False,
                    "code": "lock_timeout",
                    "timeout_ms": timeout_ms,
                }
            time.sleep(retry_sec)
        except OSError as e:
            return {"ok": False, "code": "lock_acquire_failed", "err": str(e)}


def release_lock(result: Dict[str, Any]) -> None:
    """幂等释放锁。接受任意 acquire_lock 返回值，失败/重复调用都不抛。"""
    if not isinstance(result, dict) or not result.get("ok"):
        return
    lock_path = result.get("lock_dir")
    if not lock_path:
        return
    try:
        shutil.rmtree(Path(lock_path), ignore_errors=True)
    except OSError:
        pass
