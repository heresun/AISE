"""Region 探测（v3.4 P1-3）

检测策略（按优先级）：
  1. `AISE_REGION` 环境变量（cn / us / global）—— 最高优先级，用户显式 override
  2. 系统时区：含 'Asia/Shanghai' / 'Asia/Chongqing' / 'Asia/Urumqi' / 'PRC' → cn
                'America/...' → us
                其他 → global（默认）
  3. fallback：global

不做：DNS 探测、网络延迟比较（避免脱机/网络异常时 doctor 卡住）。

设计：region 仅用于推荐镜像，**不强制 override 用户配置**。
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional


SUPPORTED_REGIONS = {"cn", "us", "global"}

CN_TIMEZONES = {
    "Asia/Shanghai", "Asia/Chongqing", "Asia/Urumqi", "Asia/Harbin",
    "Asia/Kashgar", "PRC", "Asia/Hong_Kong", "Asia/Macau",
}
US_TIMEZONE_PREFIXES = ("America/",)


def _get_timezone_name() -> str:
    """获取系统 timezone 名称。失败返回空字符串。

    跨平台策略：
      - macOS / Linux：读 /etc/localtime symlink 目标
      - Windows：用 time.tzname / TZ env
      - 测试：可 monkeypatch 这个函数
    """
    # 优先尝试 zoneinfo
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        # IANA 名通常在 /etc/localtime
        path = os.readlink("/etc/localtime") if os.path.islink("/etc/localtime") else ""
        if path:
            # 类似 ../usr/share/zoneinfo/Asia/Shanghai
            parts = path.split("/zoneinfo/")
            if len(parts) == 2:
                return parts[1]
    except (OSError, ImportError):
        pass

    # fallback：TZ env / time.tzname
    tz = os.environ.get("TZ", "")
    if tz:
        return tz

    # time.tzname 给的是简称（如 "CST" / "PST"），不够精确，但能识别 CN
    try:
        names = time.tzname
        if names and "CST" in names:
            # CST 可能是 China Standard Time 也可能是 Central Standard Time（美国），
            # 不可靠。返回空让 fallback 走 global
            return ""
    except Exception:  # noqa: BLE001
        pass

    return ""


def detect_region() -> str:
    """探测当前 region。返回 'cn' / 'us' / 'global'."""
    # 1. env override
    env = os.environ.get("AISE_REGION", "").strip().lower()
    if env in SUPPORTED_REGIONS:
        return env
    # 非法 env 值 → 继续 fallback（不直接 raise）

    # 2. timezone
    tz = _get_timezone_name()
    if tz:
        if tz in CN_TIMEZONES:
            return "cn"
        for prefix in US_TIMEZONE_PREFIXES:
            if tz.startswith(prefix):
                return "us"

    # 3. fallback
    return "global"


def region_info() -> dict:
    """返回完整探测信息，便于 doctor 等工具展示。"""
    env = os.environ.get("AISE_REGION", "").strip().lower()
    tz = _get_timezone_name()
    detected = detect_region()
    if env in SUPPORTED_REGIONS:
        source = "env_var"
    elif tz in CN_TIMEZONES or (tz and any(tz.startswith(p) for p in US_TIMEZONE_PREFIXES)):
        source = "timezone"
    else:
        source = "fallback_default"
    return {
        "detected": detected,
        "source": source,
        "env_AISE_REGION": env or None,
        "timezone": tz or None,
    }
