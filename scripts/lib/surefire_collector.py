"""Maven Surefire / Failsafe XML 收集器（v3.2.5 §4.4.5.4）

Maven 默认输出：
  target/surefire-reports/TEST-*.xml   单元测试
  target/failsafe-reports/TEST-*.xml   集成测试（IT）

AISE 需要把这些 XML 收集到 $AISE_TEST_REPORT_DIR（统一一处供下游解析）。

策略：
  1. 优先 os.link()（hard-link）：同盘 O(1) + 节省 IO
  2. EXDEV / EPERM / 其他 OSError → shutil.copyfile 回退（跨盘 / NTFS hard-link 不允许）
  3. 源/目标双 copy 保留：不删源，让 Maven 重跑 / IDE 查报告依然能找到

命名避撞：surefire 与 failsafe 同名时 failsafe 加 `failsafe-` 前缀。

返回 dict：
  {
    "collected": [
      {"src": str, "dst": str, "origin": "surefire"|"failsafe",
       "method": "hard-link"|"copy"},
      ...
    ],
    "warnings": [str, ...],
  }
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List


def _collect_dir(
    src_dir: Path,
    out_dir: Path,
    origin: str,
    name_prefix: str,
    existing_names: set,
    collected: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    """扫描 src_dir 中 TEST-*.xml 并 link/copy 到 out_dir。"""
    if not src_dir.exists() or not src_dir.is_dir():
        return

    for entry in sorted(src_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.startswith("TEST-"):
            continue
        if not entry.name.endswith(".xml"):
            continue

        # 避撞：同名时加 origin 前缀
        dst_name = entry.name
        if dst_name in existing_names:
            dst_name = f"{name_prefix}{entry.name}"
        existing_names.add(dst_name)

        dst = out_dir / dst_name
        # 已存在的 dst 先清掉（os.link 不允许 dst 存在）
        if dst.exists():
            try:
                dst.unlink()
            except OSError as e:
                warnings.append(f"无法移除既有 dst {dst}: {e}")
                continue

        method = "hard-link"
        try:
            os.link(str(entry), str(dst))
        except OSError:
            # EXDEV(跨盘) / EPERM(权限) / NTFS 等场景回退 copy
            try:
                shutil.copyfile(str(entry), str(dst))
                method = "copy"
            except OSError as e:
                warnings.append(f"无法 link/copy {entry} → {dst}: {e}")
                continue

        collected.append({
            "src": str(entry.resolve()),
            "dst": str(dst.resolve()),
            "origin": origin,
            "method": method,
        })


def collect_surefire_xmls(project_root: Path, out_dir: Path) -> Dict[str, Any]:
    """主入口：扫描 project_root 下的 surefire/failsafe reports 并收集到 out_dir。"""
    project_root = Path(project_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    collected: List[Dict[str, Any]] = []
    warnings: List[str] = []
    existing_names: set = set()

    surefire_dir = project_root / "target" / "surefire-reports"
    failsafe_dir = project_root / "target" / "failsafe-reports"

    # surefire 先收（普通情况它占大头）
    _collect_dir(surefire_dir, out_dir, "surefire", "surefire-", existing_names, collected, warnings)
    _collect_dir(failsafe_dir, out_dir, "failsafe", "failsafe-", existing_names, collected, warnings)

    return {"collected": collected, "warnings": warnings}
