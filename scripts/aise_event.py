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
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import event_runner as er
from lib import evidence as ev_lib
from lib import surefire_collector as sc_lib


# 默认允许的 target glob（Spike-1 简化：白名单写死）
DEFAULT_ALLOWED_PATTERNS = ["./pkg/**", "./internal/**", "./cmd/**", "./...", "./pkg/...", "./internal/...", "./cmd/..."]
# Maven 测试选择器白名单（v3.2.5 §4.4.5：跨 pipe 各自定义 allowed_patterns）
DEFAULT_MVN_ALLOWED_PATTERNS = ["*Test", "*Tests", "*IT", "*Test#*", "*Tests#*", "*IT#*", "*"]
# pytest 路径白名单（默认 tests/ 目录 + test_*.py / *_test.py）
DEFAULT_PYTEST_ALLOWED_PATTERNS = [
    "tests", "tests/**", "./tests", "./tests/**",
    "test_*.py", "*_test.py", "tests/test_*.py", "tests/**/test_*.py",
    ".",
]
# Jest 测试选择器（默认 *.test.js 文件 + 路径）
DEFAULT_JEST_ALLOWED_PATTERNS = [
    "*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts",
    "**/*.test.js", "**/*.test.ts",
    "tests/**", "__tests__/**", "src/**",
    ".",
]


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


def _parse_surefire_targets(junit_files: List[Path]) -> List[dict]:
    """聚合多个 Surefire/Failsafe XML → actual_test_targets[]（v3.2.5 §4.1）

    每个 testcase 携带 source_artifact_path（去重 key 一部分），
    供 Surefire vs Failsafe 同名 testcase 按 source 区分（应 P1-B）。
    """
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
            pkg = suite.attrib.get("name", "")  # Surefire 通常是 fully-qualified class name
            for case in suite.findall("testcase"):
                classname = case.attrib.get("classname", "")
                name = case.attrib.get("name", "")
                # Surefire 把 package 放在 classname（"sample.CalcTest"），suite.name 同
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


def run_mvn_surefire_pipe(
    project_root: Path,
    out_dir: Path,
    run_id: str,
    mvn_bin: str,
    extra_system_props: List[str],
    skip_failsafe: bool = True,
) -> tuple[int, dict]:
    """执行 mvn test [systemProps] → collect_surefire_xmls → 聚合 actual_test_targets。

    extra_system_props: ["forceFail=true", ...]，会被转为 -DforceFail=true。
    skip_failsafe: True 时仅跑 surefire（mvn test），False 跑 surefire + failsafe（mvn verify）。
    """
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
    stdout_dump.write_text(mvn_proc.stdout, encoding="utf-8")
    stderr_dump.write_text(mvn_proc.stderr, encoding="utf-8")

    window_end = _now_ms()
    test_ok = (mvn_proc.returncode == 0)

    # 收 surefire/failsafe XML 到 out_dir
    collect_result = sc_lib.collect_surefire_xmls(project_root, out_dir)
    collected = collect_result["collected"]

    # 解析聚合 actual_test_targets
    junit_paths = [Path(r["dst"]) for r in collected]
    actual_targets = _parse_surefire_targets(junit_paths)

    # 收 evidence：每个 collected XML + stdout/stderr dump
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

    pipeline_ok = len(collected) > 0  # 至少一个 JUnit XML 落盘视为 pipeline 健康

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


def _parse_pytest_targets(junit_path: Path) -> List[dict]:
    """解析 pytest 产出的 JUnit XML → actual_test_targets[]。

    pytest 默认结构：<testsuite name="pytest" ...><testcase classname="tests.test_calc"
    name="test_add" file="tests/test_calc.py" line="..."/>。
    parent_package 取 classname 最后一个 `.` 之前的部分（去掉 ClassName 或 module 末段）。
    若 classname 无 `.`，取整体作为 package。
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


def run_pytest_pipe(
    project_root: Path,
    targets: List[str],
    out_dir: Path,
    run_id: str,
    pytest_bin: str,
    extra_args: List[str],
) -> tuple[int, dict]:
    """spawn `pytest --junit-xml=$OUT/junit.xml $targets $extra_args`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"pytest-{run_id}.stdout.log"
    stderr_dump = out_dir / f"pytest-{run_id}.stderr.log"

    window_start = _now_ms()

    # 用 python3 -m pytest 形式更稳健（pytest_bin 可能是 `pytest` 也可能是 python3 路径）
    if pytest_bin == "python3 -m pytest" or pytest_bin == "python -m pytest":
        cmd = pytest_bin.split() + [f"--junit-xml={junit_path}"]
    else:
        cmd = [pytest_bin, f"--junit-xml={junit_path}"]
    cmd += list(extra_args or [])
    if targets:
        cmd += targets

    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    stdout_dump.write_text(proc.stdout, encoding="utf-8")
    stderr_dump.write_text(proc.stderr, encoding="utf-8")

    window_end = _now_ms()
    test_ok = (proc.returncode == 0)
    junit_ok = junit_path.exists() and junit_path.stat().st_size > 0
    if junit_ok:
        try:
            ET.parse(junit_path)
        except ET.ParseError:
            junit_ok = False

    artifacts = []
    for path, source in [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")]:
        ev = ev_lib.collect_artifact(
            path=path,
            runner="pytest-junitxml",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)
    ev_path = ev_lib.write_evidence(artifacts, project_root, run_id=run_id)

    actual_targets = _parse_pytest_targets(junit_path)

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


def _parse_jest_targets(junit_path: Path) -> List[dict]:
    """解析 jest-junit 产出的 JUnit XML → actual_test_targets[]。

    jest-junit 默认结构：
      <testsuites name="jest tests">
        <testsuite name="calc" file="calc.test.js">
          <testcase classname="calc add" name="add"/>
          <testcase classname="calc isEven" name="isEven"/>
    classname 默认是 "describeBlock testName"，name 是 testName。
    parent_package = testsuite.file 的目录部分 + 文件名（无扩展）作为模块标识。
    parent_file 取 testsuite.file。
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
        suite_name = suite.attrib.get("name", "")  # 通常是顶层 describe 名
        suite_file = suite.attrib.get("file", "")
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            # parent_package：用顶层 describe 名作为"包"概念（Jest 没有原生 package）
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


def run_jest_pipe(
    project_root: Path,
    targets: List[str],
    out_dir: Path,
    run_id: str,
    extra_args: List[str],
) -> tuple[int, dict]:
    """spawn npx jest 在 project_root 跑测试，jest-junit reporter 落盘 JUnit XML。

    依赖 fixture 内 package.json 已配置 jest + jest-junit dev deps 并 npm install。
    JUnit XML 路径通过 JEST_JUNIT_OUTPUT_DIR / JEST_JUNIT_OUTPUT_NAME 环境变量控制。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_name = f"junit-{run_id}.xml"
    junit_path = out_dir / junit_name
    stdout_dump = out_dir / f"jest-{run_id}.stdout.log"
    stderr_dump = out_dir / f"jest-{run_id}.stderr.log"

    window_start = _now_ms()

    # 优先用 fixture 内 ./node_modules/.bin/jest，避免 npx 联网
    local_jest = project_root / "node_modules" / ".bin" / "jest"
    if local_jest.exists():
        cmd = [str(local_jest)]
    else:
        cmd = ["npx", "--no-install", "jest"]

    cmd += list(extra_args or [])
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
    stdout_dump.write_text(proc.stdout, encoding="utf-8")
    stderr_dump.write_text(proc.stderr, encoding="utf-8")

    window_end = _now_ms()
    test_ok = (proc.returncode == 0)
    junit_ok = junit_path.exists() and junit_path.stat().st_size > 0
    if junit_ok:
        try:
            ET.parse(junit_path)
        except ET.ParseError:
            junit_ok = False

    artifacts = []
    for path, source in [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")]:
        ev = ev_lib.collect_artifact(
            path=path,
            runner="jest-junit",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)
    ev_path = ev_lib.write_evidence(artifacts, project_root, run_id=run_id)

    actual_targets = _parse_jest_targets(junit_path)

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


def _parse_cargo_targets(junit_path: Path) -> List[dict]:
    """解析 cargo2junit 产出的 JUnit XML → actual_test_targets[]。

    cargo2junit 输出：
      <testsuites>
        <testsuite name="my_crate"><testcase name="tests::test_add" classname="tests"/>
    name 含 `::` 分隔的模块路径 + 函数名。parent_package = 模块路径。
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
            # cargo2junit 实测：testcase.classname 已是 Rust 模块路径（如 "tests"），
            # testcase.name 是测试函数短名（如 "test_add"）
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


def run_cargo_pipe(
    project_root: Path,
    out_dir: Path,
    run_id: str,
    cargo_bin: str,
    cargo2junit_bin: str,
    extra_args: List[str],
) -> tuple[int, dict]:
    """spawn `cargo test --no-fail-fast -- -Z unstable-options --format json --report-time`
    或 `cargo test -- -Z unstable-options --format json` 然后管道给 cargo2junit。

    cargo2junit 期望 stdin 是 cargo test --format json 输出。
    注意：JSON 格式输出在 stable 上需要 `--format` flag 通过 `--`; 部分版本需要 nightly。
    Spike-3 采用 `RUSTC_BOOTSTRAP=1` + `-Z unstable-options` 在 stable toolchain 强制启用。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    junit_path = out_dir / f"junit-{run_id}.xml"
    stdout_dump = out_dir / f"cargo-{run_id}.stdout.log"
    stderr_dump = out_dir / f"cargo-{run_id}.stderr.log"

    window_start = _now_ms()

    # cargo test --no-run 先编译，再用 --no-fail-fast + json
    cargo_cmd = [cargo_bin, "test", "--no-fail-fast", "--",
                 "-Z", "unstable-options", "--format", "json", "--report-time"]
    cargo_cmd += list(extra_args or [])

    env = os.environ.copy()
    env["RUSTC_BOOTSTRAP"] = "1"  # stable toolchain 启用 unstable -Z

    cargo_proc = subprocess.run(
        cargo_cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        env=env,
    )
    stdout_dump.write_text(cargo_proc.stdout, encoding="utf-8")
    stderr_dump.write_text(cargo_proc.stderr, encoding="utf-8")

    # cargo test stdout 夹杂非 JSON 行（Compiling / Finished / Running unittests ...）
    # cargo2junit 期望纯 JSON 流 → 过滤
    json_lines = [
        line for line in cargo_proc.stdout.splitlines()
        if line.strip().startswith("{") and line.strip().endswith("}")
    ]
    cargo_json = "\n".join(json_lines)

    junit_proc = subprocess.run(
        [cargo2junit_bin],
        cwd=str(project_root),
        input=cargo_json,
        capture_output=True,
        text=True,
    )
    if junit_proc.stdout:
        junit_path.write_text(junit_proc.stdout, encoding="utf-8")

    window_end = _now_ms()
    test_ok = (cargo_proc.returncode == 0)
    junit_ok = junit_path.exists() and junit_path.stat().st_size > 0
    if junit_ok:
        try:
            ET.parse(junit_path)
        except ET.ParseError:
            junit_ok = False

    artifacts = []
    for path, source in [(junit_path, "junit_xml"), (stdout_dump, "stdout_dump"), (stderr_dump, "stdout_dump")]:
        ev = ev_lib.collect_artifact(
            path=path,
            runner="cargo-test-junit",
            window_start_ms=window_start,
            window_end_ms=window_end,
            source=source,
            ok=test_ok,
            project_root=project_root,
        )
        if ev:
            artifacts.append(ev)
    ev_path = ev_lib.write_evidence(artifacts, project_root, run_id=run_id)

    actual_targets = _parse_cargo_targets(junit_path)

    summary = {
        "pipe": "cargo-test-junit",
        "run_id": run_id,
        "project_root": str(project_root),
        "junit_xml": str(junit_path),
        "stdout_dump": str(stdout_dump),
        "stderr_dump": str(stderr_dump),
        "evidence_jsonl": str(ev_path),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "test_exit_code": cargo_proc.returncode,
        "junit_exit_code": junit_proc.returncode,
        "actual_test_targets": actual_targets,
        "test_ok": test_ok,
        "junit_ok": junit_ok,
    }

    if not junit_ok:
        return 2, summary
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
    parser.add_argument("--mvn-system-property", action="append", default=[],
                        help="mvn-surefire 专用：透传 -DKEY=VALUE，可重复")
    parser.add_argument("--mvn-include-failsafe", action="store_true",
                        help="mvn-surefire 改跑 mvn verify 含 failsafe")
    parser.add_argument("--pytest-extra-arg", action="append", default=[],
                        help="pytest-junitxml 专用：透传额外 pytest 参数（如 -k name）")
    parser.add_argument("--jest-extra-arg", action="append", default=[],
                        help="jest-junit 专用：透传额外 jest 参数")
    parser.add_argument("--cargo-extra-arg", action="append", default=[],
                        help="cargo-test-junit 专用：透传额外 cargo test 参数")
    parser.add_argument("--cargo2junit-bin", default=None,
                        help="cargo-test-junit 专用：cargo2junit 可执行路径（默认 PATH 上）")
    args = parser.parse_args()

    # Step 1: preflight
    ok, info = er.preflight_pipe(args.pipe)
    if not ok:
        if info.get("code") == "pipe_unknown":
            print(f"[AISE-event] FAIL: 未知 pipe {args.pipe}", file=sys.stderr)
            return 2
        _emit_preflight_diagnostic(info)
        return er.EXIT_CODE_TOOL_MISSING

    # Step 2: defense in depth（每个 pipe 用各自的默认 allowed_patterns）
    if args.allowed_pattern:
        allowed = args.allowed_pattern
    elif args.pipe == "mvn-surefire":
        allowed = DEFAULT_MVN_ALLOWED_PATTERNS
    elif args.pipe == "pytest-junitxml":
        allowed = DEFAULT_PYTEST_ALLOWED_PATTERNS
    elif args.pipe == "jest-junit":
        allowed = DEFAULT_JEST_ALLOWED_PATTERNS
    elif args.pipe == "cargo-test-junit":
        allowed = ["*"]  # cargo target 是 crate 内测试函数路径，简化放行
    else:
        allowed = DEFAULT_ALLOWED_PATTERNS
    if args.target:
        targets = args.target
    elif args.pipe == "mvn-surefire":
        targets = []
    elif args.pipe == "pytest-junitxml":
        targets = ["tests"]
    elif args.pipe in ("jest-junit", "cargo-test-junit"):
        targets = []
    else:
        targets = ["./..."]
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
    elif args.pipe == "mvn-surefire":
        exit_code, summary = run_mvn_surefire_pipe(
            project_root=project_root,
            out_dir=out_dir,
            run_id=run_id,
            mvn_bin=info["found"],
            extra_system_props=args.mvn_system_property,
            skip_failsafe=not args.mvn_include_failsafe,
        )
    elif args.pipe == "pytest-junitxml":
        exit_code, summary = run_pytest_pipe(
            project_root=project_root,
            targets=args.target,
            out_dir=out_dir,
            run_id=run_id,
            pytest_bin=info["found"],
            extra_args=args.pytest_extra_arg,
        )
    elif args.pipe == "jest-junit":
        exit_code, summary = run_jest_pipe(
            project_root=project_root,
            targets=args.target,
            out_dir=out_dir,
            run_id=run_id,
            extra_args=args.jest_extra_arg,
        )
    elif args.pipe == "cargo-test-junit":
        # info["found"] 是 cargo2junit（PIPE_DEFS bin），cargo 本身需要自己找
        cargo2junit_bin = info["found"]
        cargo_bin = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
        exit_code, summary = run_cargo_pipe(
            project_root=project_root,
            out_dir=out_dir,
            run_id=run_id,
            cargo_bin=cargo_bin,
            cargo2junit_bin=cargo2junit_bin,
            extra_args=args.cargo_extra_arg,
        )
    else:
        print(f"[AISE-event] Spike-3 已支持 go/mvn/pytest/jest/cargo；{args.pipe} 未识别",
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
