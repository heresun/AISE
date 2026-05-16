"""evidence.verify_evidence 的 mtime 容忍边界测试（v3.2.5 §12.2 P1-A）

验证 ±tolerance_ms 单边方案的精确性：
  - 生成端不扩窗口（aise_event.py 已遵守）
  - 校验端单次双边各扩 tolerance，避免 v3.2.4 时代的 3 倍叠加

边界矩阵：
  | actual_mtime offset from window | tolerance_ms | expected   |
  |---------------------------------|--------------|------------|
  | 0 (恰好在窗口内)                | 2000         | PASS       |
  | window_end + 1 ms               | 2000         | PASS       |
  | window_end + 999 ms             | 2000         | PASS       |
  | window_end + 1999 ms            | 2000         | PASS       |
  | window_end + 2000 ms            | 2000         | PASS（边界）|
  | window_end + 2001 ms            | 2000         | FAIL       |
  | window_end + 3000 ms            | 2000         | FAIL       |
  | window_start - 1 ms             | 2000         | PASS       |
  | window_start - 1999 ms          | 2000         | PASS       |
  | window_start - 2001 ms          | 2000         | FAIL       |

注意：文件系统 mtime 精度限制：
  - macOS APFS: 纳秒级（os.utime 接受 float seconds → 纳秒）
  - macOS HFS+: 1 秒级（旧）
  - Linux ext4: 1 纳秒
  - Windows NTFS: 100 纳秒
本测试基于 APFS 行为（mac 当前默认）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from lib import evidence as ev_lib


@pytest.fixture
def artifact_setup(tmp_path: Path) -> dict:
    """建一个 artifact 文件 + 写好 evidence.jsonl，返回上下文便于操控 mtime。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    art = proj / "junit.xml"
    art.write_text("<testsuite/>", encoding="utf-8")

    window_start = int(time.time() * 1000) - 100  # 100ms 前
    window_end = window_start + 200  # 持续 200ms

    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    record = {
        "runner": "test",
        "artifact_path": "junit.xml",
        "sha256": sha,
        "mtime_ms": int(art.stat().st_mtime * 1000),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "bytes": art.stat().st_size,
        "source": "junit_xml",
        "ok": True,
    }
    ev_path = proj / "evidence.jsonl"
    ev_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    return {
        "project_root": proj,
        "artifact": art,
        "evidence_path": ev_path,
        "record": record,
        "window_start": window_start,
        "window_end": window_end,
    }


def _set_mtime_ms(path: Path, mtime_ms: int) -> None:
    sec = mtime_ms / 1000.0
    os.utime(path, (sec, sec))


def _rewrite_sha(ctx: dict) -> None:
    """文件 mtime 变了但内容不变，sha256 仍一致。但若我们也改内容，需重算。
    这里不改内容，但 record 中 sha 已是原 sha，故无需重写。预留接口给将来扩展。"""
    pass


# ----------------------------- 正向窗口内 -----------------------------


@pytest.mark.parametrize("offset_ms", [0, 1, 100, 999, 1999, 2000])
def test_mtime_within_or_at_upper_boundary_passes(
    artifact_setup: dict, offset_ms: int
) -> None:
    """window_end + offset (0 ≤ offset ≤ tolerance) → PASS。"""
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + offset_ms)
    ok, violations = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=2000
    )
    assert ok is True, f"offset=+{offset_ms} ms 应在容忍内: {violations}"


@pytest.mark.parametrize("offset_ms", [1, 999, 1999, 2000])
def test_mtime_within_or_at_lower_boundary_passes(
    artifact_setup: dict, offset_ms: int
) -> None:
    """window_start - offset (0 < offset ≤ tolerance) → PASS。"""
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_start"] - offset_ms)
    ok, violations = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=2000
    )
    assert ok is True, f"offset=-{offset_ms} ms 应在容忍内: {violations}"


# ----------------------------- 超出容忍 -----------------------------


@pytest.mark.parametrize("offset_ms", [2001, 3000, 10_000])
def test_mtime_beyond_upper_boundary_fails(
    artifact_setup: dict, offset_ms: int
) -> None:
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + offset_ms)
    ok, violations = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=2000
    )
    assert ok is False, f"offset=+{offset_ms} 应超出容忍"
    assert any(v["code"] == "evidence_window_violation" for v in violations)


@pytest.mark.parametrize("offset_ms", [2001, 5000, 60_000])
def test_mtime_beyond_lower_boundary_fails(
    artifact_setup: dict, offset_ms: int
) -> None:
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_start"] - offset_ms)
    ok, violations = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=2000
    )
    assert ok is False, f"offset=-{offset_ms} 应超出容忍"
    assert any(v["code"] == "evidence_window_violation" for v in violations)


# ----------------------------- tolerance 参数化 -----------------------------


def test_smaller_tolerance_rejects_borderline(artifact_setup: dict) -> None:
    """用更严格的 tolerance=500ms，则 +1500ms 应 FAIL。"""
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + 1500)
    ok, _ = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=500
    )
    assert ok is False


def test_larger_tolerance_accepts_otherwise_failing(artifact_setup: dict) -> None:
    """用宽松 tolerance=5000ms，则 +3000ms 应 PASS。"""
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + 3000)
    ok, _ = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=5000
    )
    assert ok is True


def test_zero_tolerance_demands_exact(artifact_setup: dict) -> None:
    """tolerance=0：mtime 必须严格落入 [window_start, window_end]。"""
    ctx = artifact_setup
    # 落在窗口内（mtime_ms 已是原文件 mtime，应在 window 区间内或非常接近）
    in_window = (ctx["window_start"] + ctx["window_end"]) // 2
    _set_mtime_ms(ctx["artifact"], in_window)
    ok, _ = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=0
    )
    assert ok is True

    # 偏移 1ms 即 FAIL（tolerance=0 无容忍）
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + 1)
    ok, _ = ev_lib.verify_evidence(
        ctx["evidence_path"], ctx["project_root"], tolerance_ms=0
    )
    assert ok is False


# ----------------------------- 默认 tolerance 常量 -----------------------------


def test_default_tolerance_is_2000ms() -> None:
    assert ev_lib.MTIME_TOLERANCE_MS == 2000


def test_default_tolerance_applied_when_not_passed(artifact_setup: dict) -> None:
    """verify_evidence 不传 tolerance_ms 时使用默认 2000."""
    ctx = artifact_setup
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + 1900)
    ok, _ = ev_lib.verify_evidence(ctx["evidence_path"], ctx["project_root"])
    assert ok is True
    _set_mtime_ms(ctx["artifact"], ctx["window_end"] + 2100)
    ok, _ = ev_lib.verify_evidence(ctx["evidence_path"], ctx["project_root"])
    assert ok is False
