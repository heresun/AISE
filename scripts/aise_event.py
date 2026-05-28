#!/usr/bin/env python3
"""AISE pipe runner CLI（v4.0 插件化架构）

用法：
  python3 aise_event.py --pipe go-test-json-to-junit \\
      --project-root tests/fixtures/go-sample \\
      --target ./pkg/sample/... \\
      --run-id spike-1-t1 \\
      [--allowed-pattern ./pkg/**]

行为：
  1. preflight_pipe(pipe_name) → 失败 exit 127 + 平台安装指引
  2. defense_in_depth_check(targets, allowed) → 失败 exit 2
  3. 通过 lib.runners 插件注册表分派到对应的 pipe runner
  4. 落盘 stdout 转储 + junit XML
  5. write_evidence() 把 (path, sha256, mtime, window) 记到 .aise/runs/<run_id>/evidence.jsonl
  6. 退出码：0 = 测试 + pipeline 都成功；1 = 测试失败但 pipeline 完整；2 = 状态异常；127 = 工具缺失

v4.0：Pipe Runner 插件化 — 每个 pipe runner 独立在 lib/runners/ 下，新增 pipe 无需修改本文件。
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
from lib.ansi import maybe_strip
from lib.runners import get_runner

# 为 test_cargo_nextest.py 保持向后兼容
from lib.runners.cargo_test_runner import _parse_targets as _parse_cargo_targets
from lib.runners.cargo_nextest_runner import _parse_targets as _parse_cargo_nextest_targets

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


def _emit_preflight_diagnostic(info: dict) -> None:
    print(f"[AISE-event] FAIL: --pipe {info.get('name')} 需要的工具 {info.get('bin')} 未安装",
          file=sys.stderr)
    print(f"  用途: {info.get('purpose', '')}", file=sys.stderr)
    print(f"  平台: {info.get('platform', '')}", file=sys.stderr)
    print(f"  安装命令: {info.get('install_hint', '')}", file=sys.stderr)
    if info.get("docs"):
        print(f"  文档: {info.get('docs')}", file=sys.stderr)


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
    parser.add_argument("--nextest-extra-arg", action="append", default=[],
                        help="cargo-nextest-junit 专用：透传额外 cargo nextest run 参数")
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
        allowed = ["*"]
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

    # Step 3: 通过插件注册表分派 pipe runner
    project_root = Path(args.project_root).resolve()
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (
        project_root / ".aise" / "runs" / run_id / "test_reports"
    )

    pipe_runner = get_runner(args.pipe)
    if pipe_runner is None:
        print(f"[AISE-event] 未知 pipe {args.pipe}", file=sys.stderr)
        return 2

    if args.pipe == "go-test-json-to-junit":
        exit_code, summary = pipe_runner(
            project_root=project_root,
            targets=targets,
            out_dir=out_dir,
            run_id=run_id,
            junit_bin=info["found"],
        )
    elif args.pipe == "mvn-surefire":
        exit_code, summary = pipe_runner(
            project_root=project_root,
            out_dir=out_dir,
            run_id=run_id,
            mvn_bin=info["found"],
            extra_system_props=args.mvn_system_property,
            skip_failsafe=not args.mvn_include_failsafe,
        )
    elif args.pipe == "pytest-junitxml":
        exit_code, summary = pipe_runner(
            project_root=project_root,
            targets=args.target,
            out_dir=out_dir,
            run_id=run_id,
            pytest_bin=info["found"],
            extra_args=args.pytest_extra_arg,
        )
    elif args.pipe == "jest-junit":
        exit_code, summary = pipe_runner(
            project_root=project_root,
            targets=args.target,
            out_dir=out_dir,
            run_id=run_id,
            extra_args=args.jest_extra_arg,
        )
    elif args.pipe == "cargo-test-junit":
        cargo2junit_bin = info["found"]
        ok_rt, rt_info = er.resolve_runtime_bin("cargo-test-junit", project_root)
        if not ok_rt:
            print(f"[AISE-event] FAIL: cargo runtime bin 缺失\n  info: {rt_info}",
                  file=sys.stderr)
            return er.EXIT_CODE_TOOL_MISSING
        exit_code, summary = pipe_runner(
            project_root=project_root,
            out_dir=out_dir,
            run_id=run_id,
            cargo_bin=rt_info["path"],
            cargo2junit_bin=cargo2junit_bin,
            extra_args=args.cargo_extra_arg,
        )
    elif args.pipe == "cargo-nextest-junit":
        ok_rt, rt_info = er.resolve_runtime_bin("cargo-nextest-junit", project_root)
        if not ok_rt:
            print(f"[AISE-event] FAIL: cargo runtime bin 缺失\n  info: {rt_info}",
                  file=sys.stderr)
            return er.EXIT_CODE_TOOL_MISSING
        exit_code, summary = pipe_runner(
            project_root=project_root,
            out_dir=out_dir,
            run_id=run_id,
            cargo_bin=rt_info["path"],
            extra_args=args.nextest_extra_arg,
        )
    else:
        print(f"[AISE-event] 不支持的 pipe：{args.pipe}", file=sys.stderr)
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
