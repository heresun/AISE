"""Spike-3 fixture：pytest 测试用例（含 PASS + 可控 FAIL）。
AISE_FIXTURE_FORCE_FAIL=1 让 test_force_failable 失败，模拟 Red 状态。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calc import add, is_even


def test_add():
    assert add(2, 3) == 5


def test_is_even():
    assert is_even(4) is True
    assert is_even(7) is False


def test_force_failable():
    if os.environ.get("AISE_FIXTURE_FORCE_FAIL") == "1":
        assert False, "forced failure via AISE_FIXTURE_FORCE_FAIL=1 (Spike-3 Red 验收)"
