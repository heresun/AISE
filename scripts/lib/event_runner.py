"""Pipe runner registry + 预检 + 防御深度白名单（v3.2.5 §4.4.5）

设计要点：
  - PIPE_DEFS：注册表（bin / 平台安装指引），Spike-1 仅 go-test-json-to-junit
  - preflight_pipe()：spawn 真实 pipeline 前检查 bin 在 PATH（exit 127）
  - defense_in_depth_check()：spawn 前对 target args 做二次白名单校验（防御深度）
  - 失败语义：缺工具 → exit 127；target 不在白名单 → exit 2

Spike-1 仅覆盖单 pipe，Spike-2/3 横向扩展其他 4 种 pipe。
"""
from __future__ import annotations

import fnmatch
import shutil
from typing import Any, Dict, Iterable, List, Tuple

from lib.preflight import detect_platform


# -------------------- exit codes --------------------

EXIT_CODE_TOOL_MISSING = 127       # POSIX command-not-found 惯例
EXIT_CODE_TARGET_BREACHED = 2      # 状态异常（manifest 违约）


# -------------------- PIPE_DEFS registry --------------------

PIPE_DEFS: Dict[str, Dict[str, Any]] = {
    "go-test-json-to-junit": {
        "bin": "go-junit-report",
        "purpose": "把 go test -json 输出转为 JUnit XML",
        "install": {
            "Darwin":  "go install github.com/jstemmer/go-junit-report/v2@latest",
            "Linux":   "go install github.com/jstemmer/go-junit-report/v2@latest",
            "Windows": "go install github.com/jstemmer/go-junit-report/v2@latest",
        },
        "docs": "https://github.com/jstemmer/go-junit-report",
    },
    "pytest-junitxml": {
        "bin": "pytest",
        "purpose": "pytest 内置 --junit-xml 产出",
        "install": {
            "Darwin":  "pip3 install pytest",
            "Linux":   "pip3 install pytest",
            "Windows": "pip install pytest",
        },
    },
    "jest-junit": {
        "bin": "jest",
        "npm_dep": "jest-junit",
        "purpose": "Jest reporter jest-junit 产出 JUnit XML",
        "install": {
            "Darwin":  "npm install --save-dev jest-junit",
            "Linux":   "npm install --save-dev jest-junit",
            "Windows": "npm install --save-dev jest-junit",
        },
    },
    "cargo-test-junit": {
        "bin": "cargo2junit",
        "purpose": "把 cargo test --message-format=json 转 JUnit",
        "install": {
            "Darwin":  "cargo install cargo2junit",
            "Linux":   "cargo install cargo2junit",
            "Windows": "cargo install cargo2junit",
        },
    },
    "mvn-surefire": {
        "bin": "mvn",
        "purpose": "Surefire/Failsafe 原生产出 JUnit XML",
        "install": {
            "Darwin":  "brew install maven",
            "Linux":   "apt install maven  # 或 sdkman install maven",
            "Windows": "winget install Apache.Maven  # 或 choco install maven",
        },
    },
}


# -------------------- preflight_pipe --------------------


def preflight_pipe(pipe_name: str) -> Tuple[bool, Dict[str, Any]]:
    """检查 pipe 工具是否可用。

    返回：
      成功 → (True, {"bin": str, "found": str, "name": pipe_name})
      未知 pipe → (False, {"code": "pipe_unknown", "name": pipe_name})
      工具缺失 → (False, {"code": "pipe_tool_missing", "bin": ..., "platform": ...,
                          "install_hint": ..., "docs": ..., "name": pipe_name})
    """
    dep = PIPE_DEFS.get(pipe_name)
    if dep is None:
        return False, {"code": "pipe_unknown", "name": pipe_name}

    bin_name = dep["bin"]
    found = shutil.which(bin_name)
    if found:
        return True, {"bin": bin_name, "found": found, "name": pipe_name}

    pf = detect_platform()
    install_hint = dep["install"].get(pf) or dep["install"].get("Linux", "")
    return False, {
        "code": "pipe_tool_missing",
        "name": pipe_name,
        "bin": bin_name,
        "purpose": dep.get("purpose", ""),
        "platform": pf,
        "install_hint": install_hint,
        "docs": dep.get("docs", ""),
    }


# -------------------- defense_in_depth_check --------------------


def _matches_any(target: str, patterns: Iterable[str]) -> bool:
    """glob 风格匹配，兼容 ** 任意深度通配。"""
    for pat in patterns:
        if fnmatch.fnmatchcase(target, pat):
            return True
        # fnmatch 不天然支持 **，手动归一：把 ** 视为 *（fnmatch 的 * 已包含 /）
        if "**" in pat:
            relaxed = pat.replace("**", "*")
            if fnmatch.fnmatchcase(target, relaxed):
                return True
    return False


def defense_in_depth_check(
    targets: List[str],
    allowed_patterns: List[str],
) -> Tuple[bool, Dict[str, Any]]:
    """spawn 前二次校验：每个 target 必须命中 allowed_patterns 之一。

    返回：
      ok → (True, {})
      违约 → (False, {"code": "pipe_target_breached_manifest",
                      "target": str, "allowed": list})
    """
    if not targets:
        return True, {}  # 空集放行
    for t in targets:
        if not _matches_any(t, allowed_patterns):
            return False, {
                "code": "pipe_target_breached_manifest",
                "target": t,
                "allowed": list(allowed_patterns),
            }
    return True, {}
