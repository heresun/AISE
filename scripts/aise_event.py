#!/usr/bin/env python3
"""AISE pipe runner CLI（v3.2.5 §4.4.5 Spike-1 实现）

用法：
  python3 aise_event.py --pipe go-test-json-to-junit \\
      --project-root tests/fixtures/go-sample \\
      --target ./pkg/sample/... \\
      --run-id spike-1-t1 \\
      [--allowed-pattern ./pkg/**]

行为：
  1. preflight_pipe(pipe_name) → 失败 exit 127 + 平台安装指引
  2. defense_in_depth_check(targets, allowed) → 失败 exit 2
  3. 按 pipe_name 决定真实命令：
     - go-test-json-to-junit: cd project-root && go test -json <targets> | go-junit-report -out <out>/junit-<run>.xml
  4. 落盘 stdout 转储 + junit XML
  5. write_evidence() 把 (path, sha256, mtime, window) 记到 .aise/runs/<run_id>/evidence.jsonl
  6. 退出码：0 = 测试 + pipeline 都成功；1 = 测试失败但 pipeline 完整；2 = 状态异常；127 = 工具缺失
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import event_runner as er
from lib import evidence as ev_lib


# 默认允许的 target glob（Spike-1 简化：白名单写死）
DEFAULT_ALLOWED_PATTERNS = ["./pkg/**", "./internal/**", "./cmd/**", "./...", "./pkg/...", "./internal/...", "./cmd/..."]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _emit_preflight_diagnostic(info: dict) -> None:
    print(f"[AISE-event] FAIL: --pipe {info.get('name')} 需要的工具 {info.get('bin')} 未安装",
          file=sys.stderr)
    print(f"  用途: {info.get('purpose', '')}", file=sys.stderr)
    print(f"  平台: {info.get('platform', '')}", file=sys.stderr)
    print(f"  安装命令: {info.get('install_hint', '')}", file=sys.stderr)
    if info.get("docs"):
        print(f"  文档: {info.get('docs')}", file=sys.stderr)


def _extract_packages_from_system_out(suite: ET.Element) -> dict:
    """fallback: 从 testsuite/system-out 中的 go test -json events 抓 Test→Package 映射。

    go-junit-report v2 在 testsuite.name 留空时，原始 JSON 会内嵌到 <system-out>。
    """
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


def _parse_junit_targets(junit_path: Path, run_id: str) -> List[dict]:
    """解析 JUnit XML → actual_test_targets[]（v3.2.5 §4.1）

    多源 provenance：
      1. 优先 testsuite.name → parent_package
      2. fallback：从 system-out 里的 go test -json events 提 Package
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


def run_go_pipe(
    project_root: Path,
    targets: List[str],
    out_dir: Path,
    run_id: str,
    junit_bin: str,
) -> tuple[int, dict]:
    """执行 go test -json <targets> | go-junit-report -out <out>/junit.xml
    返回 (exit_code, summary_dict)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"go-test-{run_id}.stdout.log"
    stderr_dump = out_dir / f"go-test-{run_id}.stderr.log"

    window_start = _now_ms()

    # spawn `go test -v -json <targets>`，stdout 通过 pipe 给 go-junit-report
    # -v 让 go-junit-report 能拿到 Package 信息填到 <testsuite name>
    go_cmd = ["go", "test", "-v", "-json"] + targets
    junit_cmd = [junit_bin, "-set-exit-code", "-out", str(junit_path)]

    # 先把 go test stdout 收下来再喂给 go-junit-report，便于 stdout dump
    go_proc = subprocess.run(
        go_cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    stdout_dump.write_text(go_proc.stdout, encoding="utf-8")
    stderr_dump.write_text(go_proc.stderr, encoding="utf-8")

    junit_proc = subprocess.run(
        junit_cmd,
        cwd=str(project_root),
        input=go_proc.stdout,
        capture_output=True,
        text=True,
    )

    window_end = _now_ms()

    test_ok = (go_proc.returncode == 0)
    # junit_ok 判定：XML 文件落盘且可解析；不依赖 junit_proc.returncode，
    # 因为 -set-exit-code 让 go-junit-report 在测试失败时也 exit 1（pipeline 本身仍正常）。
    junit_ok = junit_path.exists() and junit_path.stat().st_size > 0
    if junit_ok:
        try:
            ET.parse(junit_path)
        except ET.ParseError:
            junit_ok = False

    # 收集 evidence artifact
    artifacts = []
    for path, source in [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump")]:
        ev = ev_lib.collect_artifact(
            path=path,
            runner="go-test-json-to-junit",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)

    ev_path = ev_lib.write_evidence(artifacts, project_root, run_id=run_id)

    # 解析 actual_test_targets
    actual_targets = _parse_junit_targets(junit_path, run_id)

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

    # exit: 0 = 全 ok；1 = 测试失败但 pipeline 完整
    if not junit_ok:
        return 2, summary  # pipeline 异常视为状态异常
    return (0 if test_ok else 1), summary


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE pipe runner")
    parser.add_argument("--pipe", required=True, help="Pipe 名称（见 PIPE_DEFS）")
    parser.add_argument("--project-root", required=True, help="项目根目录")
    parser.add_argument("--target", action="append", default=[], help="测试目标（可多个）")
    parser.add_argument("--allowed-pattern", action="append", default=None,
                        help="覆盖默认 allowed_patterns")
    parser.add_argument("--run-id", default=None, help="run id（用于 evidence 目录）")
    parser.add_argument("--out-dir", default=None,
                        help="JUnit XML 输出目录（默认 .aise/runs/<run_id>/test_reports）")
    parser.add_argument("--summary-json", default=None,
                        help="把 summary 写到指定文件（默认 stdout）")
    args = parser.parse_args()

    # Step 1: preflight
    ok, info = er.preflight_pipe(args.pipe)
    if not ok:
        if info.get("code") == "pipe_unknown":
            print(f"[AISE-event] FAIL: 未知 pipe {args.pipe}", file=sys.stderr)
            return 2
        _emit_preflight_diagnostic(info)
        return er.EXIT_CODE_TOOL_MISSING

    # Step 2: defense in depth
    allowed = args.allowed_pattern if args.allowed_pattern else DEFAULT_ALLOWED_PATTERNS
    targets = args.target or ["./..."]
    ok2, info2 = er.defense_in_depth_check(targets, allowed)
    if not ok2:
        print(f"[AISE-event] FAIL: defense-in-depth 拦截 target={info2.get('target')!r}",
              file=sys.stderr)
        print(f"  allowed: {info2.get('allowed')}", file=sys.stderr)
        return er.EXIT_CODE_TARGET_BREACHED

    # Step 3: dispatch by pipe
    project_root = Path(args.project_root).resolve()
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (
        project_root / ".aise" / "runs" / run_id / "test_reports"
    )

    if args.pipe == "go-test-json-to-junit":
        exit_code, summary = run_go_pipe(
            project_root=project_root,
            targets=targets,
            out_dir=out_dir,
            run_id=run_id,
            junit_bin=info["found"],
        )
    else:
        print(f"[AISE-event] Spike-1 仅实现 go-test-json-to-junit；{args.pipe} 待 Spike-2/3",
              file=sys.stderr)
        return 2

    # Step 4: emit summary
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.summary_json:
        Path(args.summary_json).write_text(summary_text, encoding="utf-8")
    else:
        print(summary_text)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
