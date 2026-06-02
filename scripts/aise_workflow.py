#!/usr/bin/env python3
"""AISE 声明式工作流引擎 CLI（v4.0）

用法：
  # 查询下一步
  python3 aise_workflow.py --from brainstorm --exit-code 0

  # 校验工作流定义
  python3 aise_workflow.py --validate

  # 列出所有节点
  python3 aise_workflow.py --list

  退出码：0 = 成功；2 = 校验失败；3 = 工作流不存在
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.workflow_engine import Workflow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKFLOW = PROJECT_ROOT / ".aise" / "workflow.json"


def _resolve_workflow(args: argparse.Namespace) -> Path:
    p = Path(args.workflow) if args.workflow else DEFAULT_WORKFLOW
    if not p.exists():
        print(f"[AISE-workflow] 工作流文件不存在: {p}", file=sys.stderr)
        raise SystemExit(3)
    return p


def cmd_next(args: argparse.Namespace) -> int:
    wf_path = _resolve_workflow(args)
    wf = Workflow.from_file(wf_path)
    next_ids = wf.next_from(args.from_node, args.exit_code or 0)

    result = {"next": next_ids}
    for nid in next_ids:
        nd = wf.node(nid)
        if nd:
            result[nid] = nd

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    wf_path = _resolve_workflow(args)
    wf = Workflow.from_file(wf_path)
    errors = wf.validate()
    if errors:
        print(f"[AISE-workflow] 校验失败 ({len(errors)} 个错误):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2
    print(f"[AISE-workflow] 校验通过 ({len(wf.all_nodes())} 个节点, {len(wf.edges)} 条边)")
    start = wf.start_node()
    if start:
        print(f"  起点: {start}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    wf_path = _resolve_workflow(args)
    wf = Workflow.from_file(wf_path)
    nodes = wf.all_nodes()
    for nid in sorted(nodes):
        nd = wf.node(nid)
        ntype = nd.get("type", "?") if nd else "?"
        desc = nd.get("description", "") if nd else ""
        print(f"  [{ntype:16s}]  {nid:20s}  {desc}")
    print(f"\n共 {len(nodes)} 个节点, {wf.start_node() or '?'} → ...")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 声明式工作流引擎")
    parser.add_argument("--workflow", default=None,
                        help=f"工作流 JSON 路径（默认: {DEFAULT_WORKFLOW}）")
    parser.add_argument("--from", dest="from_node", default=None,
                        help="当前节点 ID（查询下一步时必填）")
    parser.add_argument("--exit-code", type=int, default=0,
                        help="当前节点退出码（默认 0）")
    parser.add_argument("--validate", action="store_true",
                        help="校验工作流定义")
    parser.add_argument("--list", action="store_true",
                        help="列出所有节点")
    parser.add_argument("--next", action="store_true",
                        help="查询下一步（默认行为，当指定 --from 时）")

    args = parser.parse_args()

    try:
        if args.validate:
            return cmd_validate(args)
        if args.list:
            return cmd_list(args)
        if args.from_node:
            return cmd_next(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 3

    print("[AISE-workflow] 请指定 --from <node>、--validate 或 --list", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
