#!/usr/bin/env python3
"""AISE 错误模式追踪（PostToolUse hook）- 跨平台 Python 版

从 stdin 读取 hook payload (JSON)，写入 .aise/error_patterns.jsonl。
静默失败，永远以 0 退出，避免阻塞工具调用。
"""
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ERROR_PATTERNS = {
    "test_fail": re.compile(r"FAIL|test fail", re.IGNORECASE),
    "type_error": re.compile(r"error TS|TypeError|type "),
    "lint_fail": re.compile(r"ESLint|lint", re.IGNORECASE),
    "compile_fail": re.compile(r"compile|compilation", re.IGNORECASE),
}
GENERAL_ERROR = re.compile(r"FAIL|Error:|Exception|error TS|error:")
WATCH_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}


def classify_error(stderr: str) -> str:
    for err_type, pattern in ERROR_PATTERNS.items():
        if pattern.search(stderr):
            return err_type
    return "runtime_error"


def main() -> None:
    # 强制 UTF-8 stdin
    try:
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

    raw = sys.stdin.read()
    if not raw:
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    tool = payload.get("tool_name", "")
    if tool not in WATCH_TOOLS:
        return

    cwd = payload.get("cwd") or str(Path.cwd())
    aise_dir = Path(cwd) / ".aise"
    if not aise_dir.exists():
        return

    response = payload.get("tool_response") or {}
    is_error = bool(response.get("is_error"))
    stderr = str(response.get("stderr") or "")
    error_type = None

    if GENERAL_ERROR.search(stderr):
        is_error = True
        error_type = classify_error(stderr)
    elif is_error:
        error_type = "tool_error"

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        cmd = tool_input.get("command")
        if cmd:
            file_path = str(cmd).split()[0] if str(cmd).strip() else ""

    content_len = 0
    if tool_input.get("content"):
        content_len += len(tool_input["content"])
    if response.get("stdout"):
        content_len += len(response["stdout"])

    entry = {
        "ts": datetime.now().isoformat(),
        "tool": tool,
        "file": file_path,
        "is_error": is_error,
        "error_type": error_type,
        "est_tokens": content_len // 4,
    }

    log_path = aise_dir / "error_patterns.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # hook 必须永远成功退出
        pass
    sys.exit(0)
