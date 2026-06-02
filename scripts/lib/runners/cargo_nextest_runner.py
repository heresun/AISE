"""cargo-nextest-junit pipe runner"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from lib.ansi import maybe_strip

from ._utils import _now_ms, check_junit_ok, collect_evidence


def _parse_targets(junit_path: Path) -> List[dict]:
    """解析 cargo nextest 产出的 JUnit XML → actual_test_targets[]

    nextest 的 JUnit 输出与 cargo2junit 格式一致：
      <testsuites><testsuite name="crate"><testcase name="tests::test_foo" classname="tests"/>
    """
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
            parent_package = classname
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
    cargo_bin: str,
    extra_args: List[str] | None = None,
) -> tuple[int, dict]:
    if extra_args is None:
        extra_args = []

    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"nextest-{run_id}.stdout.log"
    stderr_dump = out_dir / f"nextest-{run_id}.stderr.log"

    window_start = _now_ms()

    cargo_cmd = [cargo_bin, "nextest", "run", "--no-fail-fast"]
    cargo_cmd += list(extra_args)

    proc = subprocess.run(
        cargo_cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    stdout_dump.write_text(maybe_strip(proc.stdout), encoding="utf-8")
    stderr_dump.write_text(maybe_strip(proc.stderr), encoding="utf-8")

    window_end = _now_ms()
    test_ok = (proc.returncode == 0)

    nextest_root = project_root / "target" / "nextest"
    candidates = []
    if nextest_root.exists():
        for profile_dir in nextest_root.iterdir():
            jx = profile_dir / "junit.xml"
            if jx.exists():
                candidates.append((jx.stat().st_mtime, jx))
    if candidates:
        candidates.sort(reverse=True)
        src = candidates[0][1]
        try:
            junit_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass

    junit_ok = check_junit_ok(junit_path)

    ev_path = collect_evidence(
        [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")],
        runner="cargo-nextest-junit",
        window_start_ms=window_start,
        window_end_ms=window_end,
        test_ok=test_ok,
        project_root=project_root,
        run_id=run_id,
    )

    actual_targets = _parse_targets(junit_path)

    summary = {
        "pipe": "cargo-nextest-junit",
        "run_id": run_id,
        "project_root": str(project_root),
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
    "name": "cargo-nextest-junit",
    "default_allowed_patterns": [
        "./pkg/**", "./internal/**", "./cmd/**",
        "./...", "./pkg/...", "./internal/...", "./cmd/...",
    ],
    "default_targets": ["./..."],
    "accepts_targets": False,
}


def invoke(ctx) -> tuple[int, dict]:
    from lib import event_runner as er
    from .base import RuntimeBinMissing

    ok_rt, rt_info = er.resolve_runtime_bin("cargo-nextest-junit", ctx.project_root)
    if not ok_rt:
        raise RuntimeBinMissing(rt_info)
    return run(
        project_root=ctx.project_root,
        out_dir=ctx.out_dir,
        run_id=ctx.run_id,
        cargo_bin=rt_info["path"],
        extra_args=ctx.extra.get("nextest_extra_arg", []),
    )
