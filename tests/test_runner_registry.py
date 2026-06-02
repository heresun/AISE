"""Pipe runner 插件契约测试（#1 收尾）

每个 runner 模块必须导出统一契约，让 aise_event.py 不再 per-pipe if/elif：
  - SPEC: {name, default_allowed_patterns, default_targets, accepts_targets}
  - invoke(ctx): 统一入口，封装本 runner 自己的 run() 调用细节（bin/runtime/extra）

registry 自动发现 lib/runners/*_runner.py 并暴露 get_spec / get_invoke / all_specs，
新增 pipe = 新建一个模块，核心代码零改动（开闭原则）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import event_runner as er  # noqa: E402
from lib.runners import get_spec, get_invoke, all_specs  # noqa: E402


EXPECTED_PIPES = set(er.PIPE_DEFS.keys())


def test_every_pipe_has_spec() -> None:
    for pipe in EXPECTED_PIPES:
        assert get_spec(pipe) is not None, f"{pipe} 缺少 SPEC"


def test_spec_required_fields() -> None:
    for pipe in EXPECTED_PIPES:
        spec = get_spec(pipe)
        assert spec["name"] == pipe
        assert isinstance(spec["default_allowed_patterns"], list)
        assert isinstance(spec["default_targets"], list)
        assert isinstance(spec["accepts_targets"], bool)


def test_every_pipe_has_callable_invoke() -> None:
    for pipe in EXPECTED_PIPES:
        assert callable(get_invoke(pipe)), f"{pipe} 缺少 invoke"


def test_registry_covers_exactly_pipe_defs() -> None:
    """registry 暴露的 spec 集合 == PIPE_DEFS（防漏注册 / 防多注册）."""
    assert set(all_specs().keys()) == EXPECTED_PIPES


def test_mvn_and_cargo_do_not_accept_targets() -> None:
    for pipe in ("mvn-surefire", "cargo-test-junit", "cargo-nextest-junit"):
        assert get_spec(pipe)["accepts_targets"] is False, f"{pipe} 不应接受 targets"


def test_targetful_pipes_accept_targets() -> None:
    for pipe in ("go-test-json-to-junit", "pytest-junitxml", "jest-junit"):
        assert get_spec(pipe)["accepts_targets"] is True, f"{pipe} 应接受 targets"


def test_unknown_pipe_returns_none() -> None:
    assert get_spec("nonexistent-pipe") is None
    assert get_invoke("nonexistent-pipe") is None
