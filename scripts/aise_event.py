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
  2. defense_in_depth_check(targets, allowed) → 失败 exit 2（默认白名单来自 runner SPEC）
  3. 构建 RunnerContext，通过 lib.runners 插件 invoke() 分派到对应 runner
  4. runner 落盘 stdout 转储 + junit XML + write_evidence()（sha256/mtime 签收）
  5. 退出码：0 = 测试 + pipeline 都成功；1 = 测试失败但 pipeline 完整；2 = 状态异常；127 = 工具缺失

v4.0：每个 runner 在 lib/runners/ 下导出 SPEC + run + invoke，新增 pipe 无需修改本文件。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import event_runner as er
from lib.runners import get_invoke, get_spec
from lib.runners.base import RunnerContext, RuntimeBinMissing

# 为 test_cargo_nextest.py 保持向后兼容
from lib.runners.cargo_test_runner import _parse_targets as _parse_cargo_targets
from lib.runners.cargo_nextest_runner import _parse_targets as _parse_cargo_nextest_targets


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
                        help="覆盖 SPEC 默认 allowed_patterns")
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

    spec = get_spec(args.pipe)
    invoke = get_invoke(args.pipe)
    if spec is None or invoke is None:
        print(f"[AISE-event] 未知 pipe {args.pipe}", file=sys.stderr)
        return 2

    # Step 2: defense in depth（默认 allowed/targets 来自 runner SPEC）
    allowed = args.allowed_pattern or spec["default_allowed_patterns"]
    targets = args.target or spec["default_targets"]
    ok2, info2 = er.defense_in_depth_check(targets, allowed)
    if not ok2:
        print(f"[AISE-event] FAIL: defense-in-depth 拦截 target={info2.get('target')!r}",
              file=sys.stderr)
        print(f"  allowed: {info2.get('allowed')}", file=sys.stderr)
        return er.EXIT_CODE_TARGET_BREACHED

    # Step 3: 构建 ctx 并经插件 invoke 分派
    project_root = Path(args.project_root).resolve()
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (
        project_root / ".aise" / "runs" / run_id / "test_reports"
    )

    ctx = RunnerContext(
        project_root=project_root,
        targets=args.target,          # 原始 --target；各 invoke 自行决定是否填 SPEC 默认
        out_dir=out_dir,
        run_id=run_id,
        preflight_info=info,
        extra={
            "mvn_system_property": args.mvn_system_property,
            "mvn_include_failsafe": args.mvn_include_failsafe,
            "pytest_extra_arg": args.pytest_extra_arg,
            "jest_extra_arg": args.jest_extra_arg,
            "cargo_extra_arg": args.cargo_extra_arg,
            "nextest_extra_arg": args.nextest_extra_arg,
        },
    )

    try:
        exit_code, summary = invoke(ctx)
    except RuntimeBinMissing as e:
        print(f"[AISE-event] FAIL: runtime bin 缺失\n  info: {e.info}", file=sys.stderr)
        return er.EXIT_CODE_TOOL_MISSING

    # Step 4: emit summary
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.summary_json:
        Path(args.summary_json).write_text(summary_text, encoding="utf-8")
    else:
        print(summary_text)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
