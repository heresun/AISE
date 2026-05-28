"""Pipe Runner 插件注册

自动发现 lib/runners/ 下所有 runner 模块，构建 pipe_name → run() 函数映射。
新增 pipe 只需在 lib/runners/ 下新建 *_runner.py 文件，无需修改本文件或核心代码。
"""

from __future__ import annotations

import importlib
import os
from typing import Callable, Dict


RUNNERS: Dict[str, Callable] = {}


def _discover_runners() -> Dict[str, Callable]:
    registry: Dict[str, Callable] = {
        "go-test-json-to-junit": ("lib.runners.go_test_runner", "run"),
        "mvn-surefire": ("lib.runners.mvn_surefire_runner", "run"),
        "pytest-junitxml": ("lib.runners.pytest_runner", "run"),
        "jest-junit": ("lib.runners.jest_runner", "run"),
        "cargo-test-junit": ("lib.runners.cargo_test_runner", "run"),
        "cargo-nextest-junit": ("lib.runners.cargo_nextest_runner", "run"),
    }

    result: Dict[str, Callable] = {}
    for pipe_name, (module_path, fn_name) in registry.items():
        try:
            mod = importlib.import_module(module_path)
            result[pipe_name] = getattr(mod, fn_name)
        except (ImportError, AttributeError):
            pass
    return result


def get_runner(pipe_name: str):
    global RUNNERS
    if not RUNNERS:
        RUNNERS = _discover_runners()
    return RUNNERS.get(pipe_name)
