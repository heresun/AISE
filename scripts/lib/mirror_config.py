"""镜像源配置（v3.4 P1-3）

策略：
  - 不直接修改用户配置文件（敏感）；只输出建议命令
  - 5 类工具：brew / maven / pip / npm / cargo
  - region=cn → 阿里云 / 清华 / 中科大；region=global → 不推荐（用 default）

每个 mirror 配置包含：
  - url: 镜像 URL（用户可 verify）
  - setup_command: 单行命令告诉用户怎么生效
  - file_path: 可选，提示用户配置文件位置（用于手动检查）
"""
from __future__ import annotations

from typing import Any, Dict


# CN region 推荐镜像（在 Spike-2 真实验证过 aliyun maven 镜像可用）
_CN_MIRRORS: Dict[str, Dict[str, Any]] = {
    "brew": {
        "url": "https://mirrors.ustc.edu.cn/brew.git",
        "setup_command": (
            "git -C \"$(brew --repo)\" remote set-url origin "
            "https://mirrors.ustc.edu.cn/brew.git\n"
            "git -C \"$(brew --repo homebrew/core)\" remote set-url origin "
            "https://mirrors.ustc.edu.cn/homebrew-core.git\n"
            "export HOMEBREW_BOTTLE_DOMAIN=https://mirrors.ustc.edu.cn/homebrew-bottles"
        ),
        "doc": "https://mirrors.ustc.edu.cn/help/brew.git.html",
    },
    "maven": {
        "url": "https://maven.aliyun.com/repository/public",
        "setup_command": (
            "# 在 ~/.m2/settings.xml 的 <mirrors> 中添加：\n"
            "<mirror>\n"
            "  <id>aliyunmaven</id>\n"
            "  <mirrorOf>*</mirrorOf>\n"
            "  <url>https://maven.aliyun.com/repository/public</url>\n"
            "</mirror>\n"
            "# 或在项目内 .mvn/settings.xml + .mvn/maven.config（推荐）"
        ),
        "doc": "https://developer.aliyun.com/mirror/maven",
        "file_path": "~/.m2/settings.xml or <project>/.mvn/settings.xml",
    },
    "pip": {
        "url": "https://mirrors.aliyun.com/pypi/simple/",
        "setup_command": (
            "pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/\n"
            "# 或临时：pip install -i https://mirrors.aliyun.com/pypi/simple/ <pkg>"
        ),
        "doc": "https://developer.aliyun.com/mirror/pypi",
        "file_path": "~/.pip/pip.conf (Linux/macOS) or %APPDATA%/pip/pip.ini (Windows)",
    },
    "npm": {
        "url": "https://registry.npmmirror.com",
        "setup_command": (
            "npm config set registry https://registry.npmmirror.com\n"
            "# 或临时：npm install --registry=https://registry.npmmirror.com"
        ),
        "doc": "https://npmmirror.com/",
        "file_path": "~/.npmrc",
    },
    "cargo": {
        "url": "https://mirrors.ustc.edu.cn/crates.io-index",
        "setup_command": (
            "# 在 ~/.cargo/config.toml 添加：\n"
            "[source.crates-io]\n"
            "replace-with = 'ustc'\n"
            "[source.ustc]\n"
            "registry = \"sparse+https://mirrors.ustc.edu.cn/crates.io-index/\""
        ),
        "doc": "https://mirrors.ustc.edu.cn/help/crates.io-index.html",
        "file_path": "~/.cargo/config.toml",
    },
}


_GLOBAL_MIRRORS: Dict[str, Dict[str, Any]] = {
    "brew": {"url": "", "setup_command": "default (no override)"},
    "maven": {"url": "", "setup_command": "default Maven Central"},
    "pip": {"url": "", "setup_command": "default PyPI"},
    "npm": {"url": "", "setup_command": "default npmjs.org"},
    "cargo": {"url": "", "setup_command": "default crates.io"},
}


def get_mirrors(region: str) -> Dict[str, Dict[str, Any]]:
    """根据 region 返回工具镜像建议。

    region:
      - "cn"     → 国内镜像（aliyun / ustc / tuna）
      - "us"     → 不需要 override（与 global 同）
      - "global" → 不推荐 override
      - 其他     → 安全返回 {}（不抛异常）
    """
    if region == "cn":
        return _CN_MIRRORS
    if region in {"us", "global"}:
        return _GLOBAL_MIRRORS
    return {}
