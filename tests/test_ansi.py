"""scripts/lib/ansi.py 单元测试（v3.4 P2-1）

去除 ANSI escape sequences，让 stdout/stderr dump 在文本编辑器中可读、可
grep。覆盖：SGR / CSI / OSC / CR + 复杂多颜色 + 跨行。
"""
from __future__ import annotations

import pytest

from lib.ansi import strip_ansi, should_strip_ansi


# ----------------------------- strip_ansi 基础 -----------------------------


def test_strip_ansi_empty_string() -> None:
    assert strip_ansi("") == ""


def test_strip_ansi_no_escape() -> None:
    """纯文本不改动。"""
    text = "Hello, World!\nLine 2\n"
    assert strip_ansi(text) == text


def test_strip_ansi_basic_sgr() -> None:
    """SGR (Select Graphic Rendition) `\\x1b[<N>m`."""
    text = "\x1b[31mRED\x1b[0m normal"
    assert strip_ansi(text) == "RED normal"


def test_strip_ansi_complex_sgr() -> None:
    """带多个参数的 SGR：\\x1b[1;31;42m."""
    text = "\x1b[1;31;42mBOLD RED ON GREEN\x1b[0m"
    assert strip_ansi(text) == "BOLD RED ON GREEN"


def test_strip_ansi_256_color() -> None:
    """256 色 / truecolor：\\x1b[38;5;208m / \\x1b[38;2;255;128;0m."""
    text = "\x1b[38;5;208mORANGE\x1b[0m \x1b[38;2;255;128;0mTRUE\x1b[0m"
    assert strip_ansi(text) == "ORANGE TRUE"


def test_strip_ansi_csi_cursor() -> None:
    """CSI cursor 控制（光标移动等）：\\x1b[2J / \\x1b[H."""
    text = "\x1b[2J\x1b[H\x1b[1;1HCleared"
    assert strip_ansi(text) == "Cleared"


def test_strip_ansi_osc() -> None:
    """OSC (Operating System Command)：\\x1b]0;title\\x07 或 \\x1b\\\\."""
    text = "\x1b]0;my title\x07Hello"
    assert strip_ansi(text) == "Hello"


def test_strip_ansi_multiline() -> None:
    text = "\x1b[32mINFO\x1b[0m line 1\n\x1b[33mWARN\x1b[0m line 2\n"
    assert strip_ansi(text) == "INFO line 1\nWARN line 2\n"


def test_strip_ansi_preserves_newlines_and_tabs() -> None:
    """新行、tab 等可见空白不应被移除（vs ANSI 控制字符）."""
    text = "\x1b[32mok\x1b[0m\tdetail\n"
    assert strip_ansi(text) == "ok\tdetail\n"


def test_strip_ansi_strips_carriage_return_in_progress_bars() -> None:
    """mvn / cargo 用 \\r 覆盖同行进度条 → 默认保留 \\r 让 dump 可读；
    保守策略：strip_ansi 不动 \\r（避免破坏内容语义）."""
    text = "Downloading\r"
    assert strip_ansi(text) == "Downloading\r"


# ----------------------------- 真实样本 -----------------------------


def test_strip_ansi_mvn_typical_output() -> None:
    """Maven 启用颜色时典型输出（节选）."""
    raw = (
        "\x1b[1;94m[INFO]\x1b[m Scanning for projects...\n"
        "\x1b[1;94m[INFO]\x1b[m \n"
        "\x1b[1;94m[INFO]\x1b[m \x1b[1m-------------------------< \x1b[36maise.spike2:sample\x1b[m\x1b[1m >--------------------------\x1b[m\n"
    )
    clean = strip_ansi(raw)
    assert "\x1b" not in clean
    assert "[INFO] Scanning for projects..." in clean
    assert "aise.spike2:sample" in clean


def test_strip_ansi_cargo_typical_output() -> None:
    """cargo 启用颜色时典型输出（节选）."""
    raw = "\x1b[1m\x1b[32m   Compiling\x1b[0m sample v0.1.0\n"
    clean = strip_ansi(raw)
    assert "\x1b" not in clean
    assert "Compiling sample v0.1.0" in clean


def test_strip_ansi_bytes_input() -> None:
    """bytes 输入应返回 str（解码 utf-8 + 过滤）."""
    b = b"\x1b[31mRED\x1b[0m"
    assert strip_ansi(b) == "RED"


def test_strip_ansi_invalid_bytes_replaced() -> None:
    """非 utf-8 bytes 不抛 — errors='replace'."""
    b = b"\x1b[31m\xff\xfe\x1b[0m"
    result = strip_ansi(b)
    assert "\x1b" not in result
    # 非 utf-8 字节被 replace char 替代
    assert isinstance(result, str)


# ----------------------------- should_strip_ansi -----------------------------


def test_should_strip_ansi_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISE_KEEP_ANSI", raising=False)
    assert should_strip_ansi() is True


def test_should_strip_ansi_env_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    """AISE_KEEP_ANSI=1 关闭过滤."""
    monkeypatch.setenv("AISE_KEEP_ANSI", "1")
    assert should_strip_ansi() is False


def test_should_strip_ansi_env_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("AISE_KEEP_ANSI", v)
        assert should_strip_ansi() is False, f"value {v!r} 应关闭过滤"


def test_should_strip_ansi_env_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("0", "false", "no", "off", "", "  "):
        monkeypatch.setenv("AISE_KEEP_ANSI", v)
        assert should_strip_ansi() is True, f"value {v!r} 应保持默认过滤"


# ----------------------------- aise_event 集成 -----------------------------


def test_event_stdout_dump_strips_ansi_by_default(tmp_path) -> None:
    """spawn aise_event 时 stdout dump 中不应有 ESC 字符（默认过滤）.

    构造一个 fake go-junit-report：用 echo 输出带 ANSI 的内容，会被 collect 到
    stdout dump。验证 dump 内容已过滤。这里用 unit test 直接测 strip_ansi 函数
    的应用即可（端到端在 spike acceptance）.
    """
    # 写测试用样本到一个文件，模拟"dump 落盘前 strip"
    from lib.ansi import strip_ansi
    sample_dump = tmp_path / "sample.stdout.log"
    raw = "\x1b[31mTest failed\x1b[0m at line 42\n"
    sample_dump.write_text(strip_ansi(raw), encoding="utf-8")
    content = sample_dump.read_text("utf-8")
    assert "\x1b" not in content
    assert "Test failed" in content
