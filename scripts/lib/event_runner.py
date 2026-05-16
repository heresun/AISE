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
import subprocess
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
        "alt_bins": ["python3 -m pytest", "python -m pytest"],
        "purpose": "pytest 内置 --junit-xml 产出",
        "install": {
            "Darwin":  "pip3 install --user pytest",
            "Linux":   "pip3 install --user pytest",
            "Windows": "pip install --user pytest",
        },
    },
    "jest-junit": {
        "bin": "node",  # Jest 通常 fixture 内 ./node_modules/.bin/jest，preflight 仅校验 node 在 PATH
        "npm_dep": "jest-junit",
        "purpose": "Jest reporter jest-junit 产出 JUnit XML",
        "install": {
            "Darwin":  "brew install node && (cd <project> && npm install --save-dev jest jest-junit)",
            "Linux":   "apt install nodejs npm && (cd <project> && npm install --save-dev jest jest-junit)",
            "Windows": "winget install OpenJS.NodeJS && (cd <project> && npm install --save-dev jest jest-junit)",
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


def _python_module_available(python_bin: str, module: str) -> bool:
    """用实际 python -c 'import X' 验证模块在该 python 上可用。"""
    try:
        r = subprocess.run(
            [python_bin, "-c", f"import {module}"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def preflight_pipe(pipe_name: str) -> Tuple[bool, Dict[str, Any]]:
    """检查 pipe 工具是否可用。

    优先级：
      1. PATH 上的主 bin（直接命令，如 mvn / go-junit-report）
      2. alt_bins 中含 `-m` 的复合命令（如 python3 -m pytest），实际 import 验证

    返回：
      成功 → (True, {"bin": str, "found": str, "name": pipe_name, "via": "path"|"alt"})
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
        return True, {"bin": bin_name, "found": found, "name": pipe_name, "via": "path"}

    # 尝试 alt_bins（python -m 形式）
    for alt in dep.get("alt_bins", []):
        if " -m " not in alt:
            continue
        parts = alt.split()
        py_bin = shutil.which(parts[0])
        if not py_bin:
            continue
        module = parts[parts.index("-m") + 1]
        if _python_module_available(py_bin, module):
            return True, {"bin": bin_name, "found": alt, "name": pipe_name, "via": "alt"}

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


def _normalize_path(path: str) -> str:
    """跨平台路径分隔符归一：`\\` → `/`，保留其他字符不变。

    v3.3 P0-2：Windows target 通常用反斜杠（`.\\pkg\\foo`），allowed_patterns
    用正斜杠（`./pkg/**`）。归一后再 fnmatch 才能正确匹配。

    安全注意：归一仅在 fnmatch 比对前做，不改变实际文件系统调用的 target，
    且 `..\\..\\etc\\passwd` 归一后仍是 `../../etc/passwd`，白名单照样拦截。
    """
    if not path:
        return path
    return path.replace("\\", "/")


def _matches_any(target: str, patterns: Iterable[str]) -> bool:
    """glob 风格匹配，兼容 ** 任意深度通配 + 跨平台路径分隔符归一。"""
    norm_target = _normalize_path(target)
    for pat in patterns:
        norm_pat = _normalize_path(pat)
        if fnmatch.fnmatchcase(norm_target, norm_pat):
            return True
        # fnmatch 不天然支持 **，手动归一：把 ** 视为 *（fnmatch 的 * 已包含 /）
        if "**" in norm_pat:
            relaxed = norm_pat.replace("**", "*")
            if fnmatch.fnmatchcase(norm_target, relaxed):
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
