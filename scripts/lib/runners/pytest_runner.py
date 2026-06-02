"""pytest-junitxml pipe runner"""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from lib.ansi import maybe_strip

from ._utils import _now_ms, check_junit_ok, collect_evidence


def _parse_targets(junit_path: Path) -> List[dict]:
    if not junit_path.exists():
        return []
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return []

    targets: List[dict] = []
    root = tree.getroot()
    suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
    rel_path = str(junit_path)
    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            file_attr = case.attrib.get("file", "")
            if "." in classname:
                parent_package = classname.rsplit(".", 1)[0]
            else:
                parent_package = classname
            targets.append({
                "kind": "testcase",
                "id": name,
                "parent_class": classname,
                "parent_package": parent_package,
                "parent_file": file_attr,
                "granularity": "testcase",
                "source": "junit_xml",
                "source_artifact_path": rel_path,
                "passed": case.find("failure") is None and case.find("error") is None,
            })
    return targets


def run(
    project_root: Path,
    targets: List[str],
    out_dir: Path,
    run_id: str,
    pytest_bin: str,
    extra_args: List[str] | None = None,
) -> tuple[int, dict]:
    if extra_args is None:
        extra_args = []

    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"pytest-{run_id}.stdout.log"
    stderr_dump = out_dir / f"pytest-{run_id}.stderr.log"

    window_start = _now_ms()

    if pytest_bin == "python3 -m pytest" or pytest_bin == "python -m pytest":
        cmd = pytest_bin.split() + [f"--junit-xml={junit_path}"]
    else:
        cmd = [pytest_bin, f"--junit-xml={junit_path}"]
    cmd += list(extra_args)
    if targets:
        cmd += targets

    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    stdout_dump.write_text(maybe_strip(proc.stdout), encoding="utf-8")
    stderr_dump.write_text(maybe_strip(proc.stderr), encoding="utf-8")

    window_end = _now_ms()
    test_ok = (proc.returncode == 0)
    junit_ok = check_junit_ok(junit_path)

    ev_path = collect_evidence(
        [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")],
        runner="pytest-junitxml",
        window_start_ms=window_start,
        window_end_ms=window_end,
        test_ok=test_ok,
        project_root=project_root,
        run_id=run_id,
    )

    actual_targets = _parse_targets(junit_path)

    summary = {
        "pipe": "pytest-junitxml",
        "run_id": run_id,
        "project_root": str(project_root),
        "targets_declared": targets,
        "junit_xml": str(junit_path),
        "stdout_dump": str(stdout_dump),
        "stderr_dump": str(stderr_dump),
        "evidence_jsonl": str(ev_path),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "test_exit_code": proc.returncode,
        "actual_test_targets": actual_targets,
        "test_ok": test_ok,
        "junit_ok": junit_ok,
    }

    if not junit_ok:
        return 2, summary
    return (0 if test_ok else 1), summary


SPEC = {
    "name": "pytest-junitxml",
    "default_allowed_patterns": [
        "tests", "tests/**", "./tests", "./tests/**",
        "test_*.py", "*_test.py", "tests/test_*.py", "tests/**/test_*.py", ".",
    ],
    "default_targets": ["tests"],
    "accepts_targets": True,
}


def invoke(ctx) -> tuple[int, dict]:
    # 复制原行为：pytest run 收到原始 --target（空则交给 pytest 自身默认），不在此填默认
    return run(
        project_root=ctx.project_root,
        targets=ctx.targets,
        out_dir=ctx.out_dir,
        run_id=ctx.run_id,
        pytest_bin=ctx.preflight_info["found"],
        extra_args=ctx.extra.get("pytest_extra_arg", []),
    )
