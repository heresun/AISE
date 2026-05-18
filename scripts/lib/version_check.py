"""工具版本号探测与比对（v3.5 P1-2）

让 aise_doctor --check-versions 跑每个工具的 --version 命令，解析版本号
（X.Y.Z 或 X.Y），与 docs/tool-compatibility-matrix.md 中的最低支持版本
对比。

设计：
- 不强制要求装所有工具（缺失 → status=skip，由原 pipe_tools check 负责报错）
- 版本解析用宽松正则，覆盖各种输出格式
- 双段版本（X.Y）自动 padding 为 (X, Y, 0) 便于元组比较
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple


# 与 docs/tool-compatibility-matrix.md 一致
MINIMUMS: Dict[str, Dict[str, Any]] = {
    "python": {
        "min": (3, 10, 0),
        "version_cmd": None,  # 用 sys.version_info 直接读，不 spawn
        "purpose": "AISE 自身运行时",
    },
    "git": {
        "min": (2, 25, 0),  # 2.28+ 推荐（-b main），2.25 起多数特性可用
        "version_cmd": ["git", "--version"],
        "purpose": "scope_check / run_init git 操作",
    },
    "go": {
        "min": (1, 21, 0),
        "version_cmd": ["go", "version"],
        "purpose": "go-test-json-to-junit pipe",
    },
    "mvn": {
        "min": (3, 6, 0),
        "version_cmd": ["mvn", "-v"],
        "purpose": "mvn-surefire pipe",
    },
    "pytest": {
        "min": (6, 0, 0),
        "version_cmd": None,  # 走 python -m pytest --version，特殊处理
        "purpose": "pytest-junitxml pipe",
    },
    "node": {
        "min": (18, 0, 0),
        "version_cmd": ["node", "--version"],
        "purpose": "jest-junit pipe",
    },
    "cargo": {
        "min": (1, 70, 0),
        "version_cmd": ["cargo", "--version"],
        "purpose": "cargo-test-junit pipe",
    },
}


_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """从任意文本中提取第一个看起来像版本号的 X.Y[.Z] → (X, Y, Z)。

    缺 patch 段时 padding 0。无匹配返回 None。
    """
    if not text:
        return None
    m = _VERSION_RE.search(text)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    return (major, minor, patch)


def meets_minimum(actual: Tuple[int, int, int], minimum: Tuple[int, int, int]) -> bool:
    """元组比较 actual ≥ minimum."""
    return actual >= minimum


def _get_python_version() -> Optional[Tuple[int, int, int]]:
    import sys
    v = sys.version_info
    return (v.major, v.minor, v.micro)


def _get_pytest_version() -> Optional[Tuple[int, int, int]]:
    """pytest --version 输出在 stderr (pytest <7) 或 stdout（pytest 7+）.

    优先 PATH 上的 pytest，fallback python3 -m pytest.
    """
    candidates = []
    if shutil.which("pytest"):
        candidates.append(["pytest", "--version"])
    if shutil.which("python3"):
        candidates.append(["python3", "-m", "pytest", "--version"])
    elif shutil.which("python"):
        candidates.append(["python", "-m", "pytest", "--version"])

    for cmd in candidates:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
            )
            output = (r.stdout or "") + " " + (r.stderr or "")
            v = parse_version(output)
            if v:
                return v
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _run_version_cmd(cmd: List[str]) -> Optional[str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        # stdout 优先，fallback stderr（git --version 走 stdout；mvn -v 也是）
        return r.stdout or r.stderr
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_tool_version(tool: str) -> Dict[str, Any]:
    """检查单个工具版本。返回 {tool, status, actual, min_version, ...}.

    status:
      - ok    : actual ≥ min
      - warn  : actual < min（仍能用但不推荐）
      - skip  : 工具未装（不报 fail，留给 pipe_tools 处理）
      - fail  : 版本探测失败（spawn 异常等）
    """
    cfg = MINIMUMS.get(tool)
    if cfg is None:
        return {"tool": tool, "status": "fail", "reason": "unknown tool"}

    min_v = cfg["min"]
    purpose = cfg.get("purpose", "")

    # 特殊处理 python / pytest
    if tool == "python":
        actual = _get_python_version()
    elif tool == "pytest":
        actual = _get_pytest_version()
    else:
        cmd = cfg["version_cmd"]
        bin_name = cmd[0]
        if not shutil.which(bin_name):
            return {
                "tool": tool,
                "status": "skip",
                "reason": f"{bin_name} not in PATH",
                "min_version": ".".join(map(str, min_v)),
                "purpose": purpose,
            }
        output = _run_version_cmd(cmd)
        actual = parse_version(output or "")

    if actual is None:
        return {
            "tool": tool,
            "status": "fail",
            "reason": "version parse failed",
            "min_version": ".".join(map(str, min_v)),
            "purpose": purpose,
        }

    status = "ok" if meets_minimum(actual, min_v) else "warn"
    return {
        "tool": tool,
        "status": status,
        "actual": ".".join(map(str, actual)),
        "min_version": ".".join(map(str, min_v)),
        "purpose": purpose,
    }


def check_all_versions() -> List[Dict[str, Any]]:
    """检查所有 MINIMUMS 中的工具版本."""
    return [check_tool_version(tool) for tool in MINIMUMS]
