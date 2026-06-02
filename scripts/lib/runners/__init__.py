"""Pipe Runner 插件注册

真·遍历 lib/runners/ 下所有 *_runner.py 模块，收集每个模块导出的
SPEC（元数据）+ run（执行函数）+ invoke（统一入口）。
新增 pipe = 新建一个 *_runner.py 文件（含 SPEC/run/invoke），无需改本文件或核心代码（开闭原则）。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Callable, Dict, Optional


_RUNNERS: Dict[str, Callable] = {}
_SPECS: Dict[str, dict] = {}
_INVOKES: Dict[str, Callable] = {}
_LOADED = False


def _discover() -> None:
    global _LOADED
    pkg_dir = Path(__file__).resolve().parent
    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod_info.name
        if not name.endswith("_runner"):
            continue
        try:
            mod = importlib.import_module(f"lib.runners.{name}")
        except ImportError:
            continue
        spec = getattr(mod, "SPEC", None)
        if not isinstance(spec, dict) or "name" not in spec:
            continue
        pipe = spec["name"]
        _SPECS[pipe] = spec
        run_fn = getattr(mod, "run", None)
        if callable(run_fn):
            _RUNNERS[pipe] = run_fn
        invoke_fn = getattr(mod, "invoke", None)
        if callable(invoke_fn):
            _INVOKES[pipe] = invoke_fn
    _LOADED = True


def _ensure() -> None:
    if not _LOADED:
        _discover()


def get_runner(pipe_name: str) -> Optional[Callable]:
    _ensure()
    return _RUNNERS.get(pipe_name)


def get_spec(pipe_name: str) -> Optional[dict]:
    _ensure()
    return _SPECS.get(pipe_name)


def get_invoke(pipe_name: str) -> Optional[Callable]:
    _ensure()
    return _INVOKES.get(pipe_name)


def all_specs() -> Dict[str, dict]:
    _ensure()
    return dict(_SPECS)
