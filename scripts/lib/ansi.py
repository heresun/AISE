"""ANSI escape sequence 过滤（v3.4 P2-1）

让 stdout / stderr dump 落盘前去除 ANSI 颜色码 / 光标控制 / OSC 等，
便于人类查 log + grep + diff。

覆盖的 escape sequence：
  - CSI (Control Sequence Introducer): `\\x1b[ ... <letter>`
    含 SGR（颜色）、cursor 控制、erase 等
  - OSC (Operating System Command): `\\x1b] ... (\\x07 | \\x1b\\\\)`
    含 window title、hyperlinks 等
  - 其他常见单字符 escape: `\\x1b<X>` 其中 X 是字母

保留：
  - `\\r` 回车（mvn 进度条用，保留让 dump 仍能体现进度）
  - `\\n` 换行
  - `\\t` tab
  - 普通可见字符

环境变量：
  - `AISE_KEEP_ANSI=1`（或 true/yes/on）：跳过过滤，保留原始内容
"""
from __future__ import annotations

import os
import re
from typing import Union


# CSI: ESC [ <params> <intermediate> <final>
#   params: [0-9;]*
#   intermediate: [ -/]*  (0x20-0x2F)
#   final: [@-~]  (0x40-0x7E)
_CSI_RE = re.compile(r"\x1b\[[0-9;:?]*[ -/]*[@-~]")

# OSC: ESC ] ... (BEL | ESC \)
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

# 其他单字符 escape：ESC <single letter>（如 \x1b N, \x1b O 等）
# 不匹配 ESC [ / ESC ]（已被前两个处理）
_SINGLE_ESC_RE = re.compile(r"\x1b[@-Z\\-_]")


def strip_ansi(text: Union[str, bytes]) -> str:
    """去除 ANSI escape sequences。返回纯文本 str。

    bytes 输入会用 utf-8 + errors='replace' 解码（防 cargo / mvn 输出含
    非 utf-8 字节时 crash）。
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    # 先 OSC（含 BEL/ESC\ 终结），避免被 CSI 误吞
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _SINGLE_ESC_RE.sub("", text)
    return text


_TRUTHY = {"1", "true", "yes", "on"}


def should_strip_ansi() -> bool:
    """读 AISE_KEEP_ANSI env var 决定是否过滤。默认 True（过滤）.

    AISE_KEEP_ANSI in {1, true, yes, on} (case-insensitive) → False（不过滤）
    """
    val = os.environ.get("AISE_KEEP_ANSI", "").strip().lower()
    if val in _TRUTHY:
        return False
    return True


def maybe_strip(text: Union[str, bytes]) -> str:
    """便利封装：按 env var 决定是否过滤。"""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if should_strip_ansi():
        return strip_ansi(text)
    return text
