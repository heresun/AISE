"""mvn-surefire pipe runner"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from lib import evidence as ev_lib
from lib import surefire_collector as sc_lib
from lib.ansi import maybe_strip

from ._utils import _now_ms


def _parse_targets(junit_files: List[Path]) -> List[dict]:
    targets: List[dict] = []
    for jx in junit_files:
        if not jx.exists():
            continue
        try:
            tree = ET.parse(jx)
        except ET.ParseError:
            continue
        root = tree.getroot()
        suites = root.findall(".//testsuite") if root.tag != "testsuite" else [root]
        rel_path = str(jx)
        for suite in suites:
            pkg = suite.attrib.get("name", "")
            for case in suite.findall("testcase"):
                classname = case.attrib.get("classname", "")
                name = case.attrib.get("name", "")
                parent_package = classname.rsplit(".", 1)[0] if "." in classname else pkg
                targets.append({
                    "kind": "testcase",
                    "id": name,
                    "parent_class": classname,
                    "parent_package": parent_package,
                    "parent_file": "",
                    "granularity": "testcase",
                    "source": "junit_xml",
                    "source_artifact_path": rel_path,
                    "passed": case.find("failure") is None and case.find("error") is None,
                })
    return targets


def run(
    project_root: Path,
    out_dir: Path,
    run_id: str,
    mvn_bin: str,
    extra_system_props: List[str] | None = None,
    skip_failsafe: bool = True,
) -> tuple[int, dict]:
    if extra_system_props is None:
        extra_system_props = []

    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_dump = out_dir / f"mvn-{run_id}.stdout.log"
    stderr_dump = out_dir / f"mvn-{run_id}.stderr.log"

    window_start = _now_ms()

    mvn_goal = "test" if skip_failsafe else "verify"
    cmd = [mvn_bin, "-B", "-q", mvn_goal]
    for kv in extra_system_props:
        cmd.append(f"-D{kv}")

    mvn_proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    stdout_dump.write_text(maybe_strip(mvn_proc.stdout), encoding="utf-8")
    stderr_dump.write_text(maybe_strip(mvn_proc.stderr), encoding="utf-8")

    window_end = _now_ms()
    test_ok = (mvn_proc.returncode == 0)

    collect_result = sc_lib.collect_surefire_xmls(project_root, out_dir)
    collected = collect_result["collected"]

    junit_paths = [Path(r["dst"]) for r in collected]
    actual_targets = _parse_targets(junit_paths)

    artifacts = []
    for rec in collected:
        ev = ev_lib.collect_artifact(
            path=Path(rec["dst"]),
            runner=f"mvn-surefire/{rec['origin']}",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source="junit_xml",
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)
    for path, source in [(stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")]:
        ev = ev_lib.collect_artifact(
            path=path,
            runner="mvn-surefire",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)

    ev_path = ev_lib.write_evidence(artifacts, project_root, run_id=run_id)

    pipeline_ok = len(collected) > 0

    summary = {
        "pipe": "mvn-surefire",
        "run_id": run_id,
        "project_root": str(project_root),
        "mvn_goal": mvn_goal,
        "extra_system_props": extra_system_props,
        "collected": collected,
        "stdout_dump": str(stdout_dump),
        "stderr_dump": str(stderr_dump),
        "evidence_jsonl": str(ev_path),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "test_exit_code": mvn_proc.returncode,
        "actual_test_targets": actual_targets,
        "test_ok": test_ok,
        "junit_ok": pipeline_ok,
        "collect_warnings": collect_result["warnings"],
    }

    if not pipeline_ok:
        return 2, summary
    return (0 if test_ok else 1), summary


SPEC = {
    "name": "mvn-surefire",
    "default_allowed_patterns": ["*Test", "*Tests", "*IT", "*Test#*", "*Tests#*", "*IT#*", "*"],
    "default_targets": [],
    "accepts_targets": False,
}


def invoke(ctx) -> tuple[int, dict]:
    return run(
        project_root=ctx.project_root,
        out_dir=ctx.out_dir,
        run_id=ctx.run_id,
        mvn_bin=ctx.preflight_info["found"],
        extra_system_props=ctx.extra.get("mvn_system_property", []),
        skip_failsafe=not ctx.extra.get("mvn_include_failsafe", False),
    )
