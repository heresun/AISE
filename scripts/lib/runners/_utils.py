from __future__ import annotations

import time
from pathlib import Path
from typing import List

from lib import evidence as ev_lib


def _now_ms() -> int:
    return int(time.time() * 1000)


def collect_evidence(
    artifacts_spec: List[tuple],
    *,
    runner: str,
    window_start_ms: int,
    window_end_ms: int,
    test_ok: bool,
    project_root: Path,
    run_id: str,
) -> str:
    artifacts = []
    for path, source in artifacts_spec:
        ev = ev_lib.collect_artifact(
            path=path,
            runner=runner,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)
    return ev_lib.write_evidence(artifacts, project_root, run_id=run_id)


def check_junit_ok(junit_path: Path) -> bool:
    """JUnit XML 文件落盘且可解析 → True"""
    import xml.etree.ElementTree as ET

    if not junit_path.exists() or junit_path.stat().st_size == 0:
        return False
    try:
        ET.parse(junit_path)
    except ET.ParseError:
        return False
    return True
