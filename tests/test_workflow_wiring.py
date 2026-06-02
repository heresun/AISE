"""工作流引擎接线测试（#2 给死引擎通电）

钉住接线正确性：
  1. templates/aise/workflow.json 通过引擎校验
  2. 关键条件跳转语义正确（verify / fuse 成功 vs 失败 去向必须不同）
  3. aise_init.py 会把 workflow.json 拷贝到使用方 .aise/
  4. commands/aise.md 通过 [node: X] 标注绑定的节点都存在于 workflow.json（防漂移）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
TEMPLATE_WF = PROJECT_ROOT / "templates" / "aise" / "workflow.json"
AISE_MD = PROJECT_ROOT / "commands" / "aise.md"

sys.path.insert(0, str(SCRIPTS))
from lib.workflow_engine import Workflow  # noqa: E402


def _wf() -> Workflow:
    return Workflow.from_file(TEMPLATE_WF)


def test_template_workflow_validates() -> None:
    assert _wf().validate() == []


def test_verify_success_goes_to_review_only() -> None:
    assert _wf().next_from("verify", exit_code=0) == ["review"]


def test_verify_failure_goes_to_task_loop_only() -> None:
    """验证失败必须只回 task_loop，绝不能同时进入 review（软门禁）。"""
    assert _wf().next_from("verify", exit_code=1) == ["task_loop"]


def test_fuse_success_goes_to_sediment() -> None:
    assert _wf().next_from("fuse", exit_code=0) == ["sediment"]


def test_fuse_failure_goes_to_task_loop() -> None:
    assert _wf().next_from("fuse", exit_code=1) == ["task_loop"]


def test_aise_init_copies_workflow_json(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPTS / "aise_init.py"), "--project-root", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert (tmp_path / ".aise" / "workflow.json").exists(), \
        "aise_init 应把 workflow.json 拷贝到使用方 .aise/"


def test_aise_md_node_tags_subset_of_workflow() -> None:
    """aise.md 用 [node: X] 绑定 workflow 节点，X 必须都存在（防文档/引擎漂移）。"""
    wf = _wf()
    md = AISE_MD.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\[node:\s*([a-z_]+)\]", md))
    assert referenced, "aise.md 应通过 [node: X] 标注绑定 workflow 节点"
    unknown = referenced - wf.all_nodes()
    assert not unknown, f"aise.md 引用了 workflow 中不存在的节点: {sorted(unknown)}"
