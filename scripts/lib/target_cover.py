"""targetCovers 救命路径（v3.2.5 §12.3 Spike-1 子集）

判定一个 actual_test_target 是否 "覆盖" 一个 declared_target，用于 TDD Gate 校验。

Spike-1 仅实现两条路径：
  1. 同 kind 同 id 完全匹配 → covers
  2. cross-kind: testcase → package（actual.parent_package == declared.id）

其他 cross-kind 组合（如 testcase→file、file→package）返回 False，由 Spike-2 扩展。
不规范输入（None / 缺 kind / 缺 id）静默返回 False，不抛异常。

API:
  target_covers(actual, declared) → bool
  all_declared_covered(actuals, declared) → (ok: bool, missing: list[dict])
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _normalize(target: Any) -> Dict[str, Any]:
    """容错读取 target dict。非 dict 或缺字段 → 返回空 dict（导致后续 False）。"""
    if not isinstance(target, dict):
        return {}
    return target


def target_covers(actual: Any, declared: Any) -> bool:
    """检查 actual 测试目标是否 cover declared 计划目标。"""
    a = _normalize(actual)
    d = _normalize(declared)
    a_kind = a.get("kind")
    d_kind = d.get("kind")
    a_id = a.get("id")
    d_id = d.get("id")

    if not a_kind or not d_kind or not d_id:
        return False

    # 路径 1：同 kind 同 id
    if a_kind == d_kind and a_id == d_id:
        return True

    # 路径 2：testcase → package（v3.2.5 §12.3.1 救命路径）
    if a_kind == "testcase" and d_kind == "package":
        parent_pkg = a.get("parent_package", "")
        return bool(parent_pkg) and parent_pkg == d_id

    # 其他 cross-kind：Spike-2 扩展
    return False


def all_declared_covered(
    actuals: List[Any],
    declared: List[Any],
) -> Tuple[bool, List[Dict[str, Any]]]:
    """检查 declared 中每个 target 是否至少被 actuals 中一个 cover。

    返回 (ok, missing)。missing 是未被覆盖的 declared targets。
    """
    actuals_list = [a for a in (actuals or []) if isinstance(a, dict)]
    missing: List[Dict[str, Any]] = []

    for d in declared or []:
        if not isinstance(d, dict):
            continue
        if not any(target_covers(a, d) for a in actuals_list):
            missing.append(d)

    return (len(missing) == 0), missing
