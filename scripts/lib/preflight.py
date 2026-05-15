"""工具存在性预检 + 平台特定安装指引

aise_verify.py 调用每个 runner 前先 preflight()，缺工具时 fail-fast 给出 brew/apt/winget
命令，避免"shell.run 失败 → 输出一堆 not found"的糟糕体验。退出码 127 与 POSIX 惯例一致。
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys


# 项目类型 → 检查的命令 + 平台安装指引
TOOL_DEPS: dict[str, dict] = {
    "mvn": {
        "bin": "mvn",
        "purpose": "运行 Maven 项目测试",
        "install": {
            "Darwin": "brew install maven",
            "Linux": "apt install maven  # 或 sdkman install maven",
            "Windows": "winget install Apache.Maven",
        },
    },
    "gradle": {
        "bin": "gradle",
        "alt_bins": ["./gradlew", "gradlew.bat"],  # 项目内 wrapper 优先
        "purpose": "运行 Gradle 项目测试",
        "install": {
            "Darwin": "brew install gradle",
            "Linux": "sdkman install gradle  # 或 apt install gradle",
            "Windows": "winget install Gradle.Gradle",
        },
    },
    "npm": {
        "bin": "npm",
        "purpose": "运行 npm test/lint/typecheck",
        "install": {
            "Darwin": "brew install node  # 或 nvm install --lts",
            "Linux": "apt install nodejs npm  # 或 nvm install --lts",
            "Windows": "winget install OpenJS.NodeJS",
        },
    },
    "pytest": {
        "bin": "pytest",
        "alt_bins": ["python3 -m pytest", "python -m pytest"],
        "purpose": "运行 Python 测试",
        "install": {
            "Darwin": "pip3 install pytest  # 或 brew install pytest",
            "Linux": "pip3 install pytest",
            "Windows": "pip install pytest",
        },
    },
    "ruff": {
        "bin": "ruff",
        "purpose": "Python 代码 lint",
        "optional": True,  # 缺失时只 warn 不阻断
        "install": {
            "Darwin": "pip3 install ruff  # 或 brew install ruff",
            "Linux": "pip3 install ruff",
            "Windows": "pip install ruff",
        },
    },
}


def detect_platform() -> str:
    """返回 'Darwin' / 'Linux' / 'Windows'，未知归 Linux"""
    s = platform.system()
    if s in ("Darwin", "Linux", "Windows"):
        return s
    return "Linux"


def _which(bin_name: str) -> str | None:
    """探测单个命令是否在 PATH 上"""
    return shutil.which(bin_name)


def _python_module_available(python_bin: str, module: str) -> bool:
    """更严格：用实际 python 跑一遍 `-c "import <module>"`，确认模块装在该 python 上"""
    try:
        r = subprocess.run(
            [python_bin, "-c", f"import {module}"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def preflight(tool_key: str, project_root=None) -> tuple[bool, dict]:
    """检查 tool_key 是否可用。返回 (ok, info_dict)。
    info_dict 在 fail 时含 install 指引 + diagnostic message。
    """
    dep = TOOL_DEPS.get(tool_key)
    if dep is None:
        return False, {"code": "preflight_unknown_tool", "tool_key": tool_key}

    # 优先级 1：项目内 wrapper（如 ./gradlew）
    if project_root is not None and dep.get("alt_bins"):
        from pathlib import Path

        for alt in dep["alt_bins"]:
            # 仅匹配文件型 wrapper（不含空格）
            if " " in alt:
                continue
            candidate = Path(project_root) / alt.lstrip("./").lstrip(".\\")
            if candidate.exists():
                return True, {"code": "ok", "found": str(candidate), "via": "wrapper"}

    # 优先级 2：PATH 上的主 bin（直接命令，如 pytest / mvn / ruff）
    found = _which(dep["bin"])
    if found:
        # pytest 特殊：直接 pytest 命令本身就保证 pytest 可用
        return True, {"code": "ok", "found": found, "via": "path"}

    # 优先级 3：alt_bins 中的复合命令（如 python3 -m pytest）
    # 这种必须实际 import 一下确认模块装在那个 python 上
    for alt in dep.get("alt_bins", []):
        if " -m " not in alt:
            continue
        parts = alt.split()
        py_bin = _which(parts[0])
        if not py_bin:
            continue
        module = parts[parts.index("-m") + 1]
        if _python_module_available(py_bin, module):
            return True, {"code": "ok", "found": alt, "via": "alt"}

    # 全部找不到
    pf = detect_platform()
    install_cmd = dep["install"].get(pf) or dep["install"].get("Linux", "(no install hint)")
    return False, {
        "code": "tool_missing",
        "tool_key": tool_key,
        "bin": dep["bin"],
        "purpose": dep["purpose"],
        "platform": pf,
        "install": install_cmd,
        "optional": dep.get("optional", False),
    }


def preflight_or_exit(tool_key: str, project_root=None) -> str:
    """便捷封装：缺工具直接 print 指引 + sys.exit(127)。返回找到的 bin。
    optional=True 的工具缺失时仅 warn 并返回空字符串。
    """
    ok, info = preflight(tool_key, project_root=project_root)
    if ok:
        return info["found"]

    if info.get("optional"):
        print(f"[AISE-preflight] WARN: optional 工具 {info['bin']} 未安装，跳过", file=sys.stderr)
        print(f"  安装指引（可选）: {info['install']}", file=sys.stderr)
        return ""

    print(f"[AISE-preflight] FAIL: 必需工具 {info['bin']} 未在 PATH 上", file=sys.stderr)
    print(f"  用途: {info['purpose']}", file=sys.stderr)
    print(f"  当前平台: {info['platform']}", file=sys.stderr)
    print(f"  安装命令: {info['install']}", file=sys.stderr)
    print(f"  装完后重跑 /aise 即可", file=sys.stderr)
    sys.exit(127)
