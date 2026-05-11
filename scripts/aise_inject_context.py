#!/usr/bin/env python3
"""AISE 结构化上下文注入（SessionStart hook）- 跨平台 Python 版

输出 JSON 给 Claude Code，作为 additionalContext。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def collect(project_root: Path, max_patterns: int) -> str:
    global_patterns = Path.home() / ".claude" / "docs" / "patterns"
    project_patterns = project_root / ".aise" / "patterns"
    project_spec = project_root / "docs" / "spec"

    lines = ["## AISE 自动注入上下文", ""]

    if project_spec.exists():
        spec_files = list(project_spec.glob("*.md"))[:3]
        if spec_files:
            lines.append("### 项目规范 (docs/spec)")
            for f in spec_files:
                lines.append(f"- {f}")
            lines.append("")

    if project_patterns.exists():
        files = sorted(
            project_patterns.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_patterns]
        if files:
            lines.append("### 项目级历史 Patterns")
            for f in files:
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
                lines.append(f"- {f.name} (最后修改: {mtime})")
            lines.append("")

    if global_patterns.exists():
        files = sorted(
            global_patterns.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_patterns]
        if files:
            lines.append("### 全局历史 Patterns")
            for f in files:
                lines.append(f"- {f}")
            lines.append("")

    progress_path = project_root / ".aise" / "progress.md"
    if progress_path.exists():
        lines.append("### AISE 当前进度")
        content_lines = progress_path.read_text(encoding="utf-8").splitlines()[:25]
        lines.extend(content_lines)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--max-patterns", type=int, default=5)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    additional_context = collect(project_root, args.max_patterns)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 不阻塞会话启动
        pass
    sys.exit(0)
