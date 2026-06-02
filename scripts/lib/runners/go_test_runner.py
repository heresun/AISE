"""go-test-json-to-junit pipe runner"""

from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from lib.ansi import maybe_strip

from ._utils import _now_ms, check_junit_ok, collect_evidence


def _parse_targets(junit_path: Path, run_id: str) -> List[dict]:
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
        suite_pkg = suite.attrib.get("name", "")
        fallback_map = _extract_packages_from_system_out(suite) if not suite_pkg else {}
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            pkg = suite_pkg or fallback_map.get(name, "") or classname
            targets.append({
                "kind": "testcase",
                "id": name,
                "parent_class": classname,
                "parent_package": pkg,
                "parent_file": "",
                "granularity": "testcase",
                "source": "junit_xml",
                "source_artifact_path": rel_path,
                "passed": case.find("failure") is None and case.find("error") is None,
            })
    return targets


def _extract_packages_from_system_out(suite: ET.Element) -> dict:
    sys_out = suite.find("system-out")
    if sys_out is None or not sys_out.text:
        return {}
    test_to_pkg: dict = {}
    for line in sys_out.text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("Test")
        pkg = ev.get("Package")
        if t and pkg and t not in test_to_pkg:
            test_to_pkg[t] = pkg
    return test_to_pkg


def run(
    project_root: Path,
    targets: List[str],
    out_dir: Path,
    run_id: str,
    junit_bin: str,
) -> tuple[int, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"go-test-{run_id}.stdout.log"
    stderr_dump = out_dir / f"go-test-{run_id}.stderr.log"

    window_start = _now_ms()

    go_cmd = ["go", "test", "-v", "-json"] + targets
    junit_cmd = [junit_bin, "-set-exit-code", "-out", str(junit_path)]

    go_proc = subprocess.run(
        go_cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    stdout_dump.write_text(maybe_strip(go_proc.stdout), encoding="utf-8")
    stderr_dump.write_text(maybe_strip(go_proc.stderr), encoding="utf-8")

    junit_proc = subprocess.run(
        junit_cmd,
        cwd=str(project_root),
        input=go_proc.stdout,
        capture_output=True,
        text=True,
    )

    window_end = _now_ms()

    test_ok = (go_proc.returncode == 0)
    junit_ok = check_junit_ok(junit_path)

    ev_path = collect_evidence(
        [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump")],
        runner="go-test-json-to-junit",
        window_start_ms=window_start,
        window_end_ms=window_end,
        test_ok=test_ok,
        project_root=project_root,
        run_id=run_id,
    )

    actual_targets = _parse_targets(junit_path, run_id)

    summary = {
        "pipe": "go-test-json-to-junit",
        "run_id": run_id,
        "project_root": str(project_root),
        "targets_declared": targets,
        "junit_xml": str(junit_path),
        "stdout_dump": str(stdout_dump),
        "evidence_jsonl": str(ev_path),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "test_exit_code": go_proc.returncode,
        "junit_exit_code": junit_proc.returncode,
        "actual_test_targets": actual_targets,
        "test_ok": test_ok,
        "junit_ok": junit_ok,
    }

    if not junit_ok:
        return 2, summary
    return (0 if test_ok else 1), summary


SPEC = {
    "name": "go-test-json-to-junit",
    "default_allowed_patterns": [
        "./pkg/**", "./internal/**", "./cmd/**",
        "./...", "./pkg/...", "./internal/...", "./cmd/...",
    ],
    "default_targets": ["./..."],
    "accepts_targets": True,
}


def invoke(ctx) -> tuple[int, dict]:
    return run(
        project_root=ctx.project_root,
        targets=ctx.targets or SPEC["default_targets"],
        out_dir=ctx.out_dir,
        run_id=ctx.run_id,
        junit_bin=ctx.preflight_info["found"],
    )
