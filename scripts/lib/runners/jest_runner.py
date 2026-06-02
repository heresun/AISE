"""jest-junit pipe runner"""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from lib import event_runner as er
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
        suite_name = suite.attrib.get("name", "")
        suite_file = suite.attrib.get("file", "")
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            parent_package = suite_name
            targets.append({
                "kind": "testcase",
                "id": name,
                "parent_class": classname,
                "parent_package": parent_package,
                "parent_file": suite_file,
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
    extra_args: List[str] | None = None,
) -> tuple[int, dict]:
    if extra_args is None:
        extra_args = []

    out_dir.mkdir(parents=True, exist_ok=True)
    junit_name = f"junit-{run_id}.xml"
    junit_path = out_dir / junit_name
    stdout_dump = out_dir / f"jest-{run_id}.stdout.log"
    stderr_dump = out_dir / f"jest-{run_id}.stderr.log"

    window_start = _now_ms()

    ok_rt, rt_info = er.resolve_runtime_bin("jest-junit", project_root)
    if not ok_rt:
        cmd = ["npx", "--no-install", "jest"]
    else:
        cmd = [rt_info["path"]]

    cmd += list(extra_args)
    if targets:
        cmd += targets

    env = os.environ.copy()
    env["JEST_JUNIT_OUTPUT_DIR"] = str(out_dir)
    env["JEST_JUNIT_OUTPUT_NAME"] = junit_name

    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env=env,
    )
    stdout_dump.write_text(maybe_strip(proc.stdout), encoding="utf-8")
    stderr_dump.write_text(maybe_strip(proc.stderr), encoding="utf-8")

    window_end = _now_ms()
    test_ok = (proc.returncode == 0)
    junit_ok = check_junit_ok(junit_path)

    ev_path = collect_evidence(
        [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")],
        runner="jest-junit",
        window_start_ms=window_start,
        window_end_ms=window_end,
        test_ok=test_ok,
        project_root=project_root,
        run_id=run_id,
    )

    actual_targets = _parse_targets(junit_path)

    summary = {
        "pipe": "jest-junit",
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
    "name": "jest-junit",
    "default_allowed_patterns": [
        "*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts",
        "**/*.test.js", "**/*.test.ts",
        "tests/**", "__tests__/**", "src/**", ".",
    ],
    "default_targets": [],
    "accepts_targets": True,
}


def invoke(ctx) -> tuple[int, dict]:
    return run(
        project_root=ctx.project_root,
        targets=ctx.targets,
        out_dir=ctx.out_dir,
        run_id=ctx.run_id,
        extra_args=ctx.extra.get("jest_extra_arg", []),
    )
