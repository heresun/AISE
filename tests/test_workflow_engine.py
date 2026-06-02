"""工作流引擎测试（v4.0）"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.workflow_engine import NODE_TYPES, Workflow


SIMPLE_WF = {
    "version": "1.0",
    "start": "init",
    "nodes": {
        "init": {"type": "script", "script": "init.py"},
        "build": {"type": "script", "script": "build.py"},
        "test": {"type": "script", "script": "test.py"},
        "deploy": {"type": "script", "script": "deploy.py"},
    },
    "edges": [
        {"from": "init", "to": "build"},
        {"from": "build", "to": "test"},
        {"from": "test", "to": "deploy"},
    ],
}

CONDITIONAL_WF = {
    "version": "1.0",
    "start": "build",
    "nodes": {
        "build": {"type": "script", "script": "build.py"},
        "test": {"type": "script", "script": "test.py"},
        "deploy": {"type": "script", "script": "deploy.py"},
        "revert": {"type": "script", "script": "revert.py"},
    },
    "edges": [
        {"from": "build", "to": "test"},
        {"from": "test", "to": "deploy", "condition": "exit_code == 0"},
        {"from": "test", "to": "revert", "condition": "exit_code == 1"},
    ],
}

FAILURE_BRANCH_WF = {
    "version": "1.0",
    "start": "verify",
    "nodes": {
        "verify": {"type": "script", "script": "verify.py"},
        "review": {"type": "script", "script": "review.py"},
        "retry": {"type": "script", "script": "retry.py"},
    },
    "edges": [
        {"from": "verify", "to": "review"},
        {"from": "verify", "to": "retry", "on_failure": True},
    ],
}


# ---------------------------------------------------------------
# 基本 DAG 遍历
# ---------------------------------------------------------------

def test_basic_linear_traversal() -> None:
    wf = Workflow(SIMPLE_WF)
    assert wf.start_node() == "init"
    assert wf.next_from("init") == ["build"]
    assert wf.next_from("build") == ["test"]
    assert wf.next_from("test") == ["deploy"]
    assert wf.next_from("deploy") == []


def test_node_lookup() -> None:
    wf = Workflow(SIMPLE_WF)
    assert wf.node("build") == {"type": "script", "script": "build.py"}
    assert wf.node("nonexistent") is None


def test_all_nodes() -> None:
    wf = Workflow(SIMPLE_WF)
    assert wf.all_nodes() == {"init", "build", "test", "deploy"}


def test_from_file(tmp_path: Path) -> None:
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(SIMPLE_WF), encoding="utf-8")
    wf = Workflow.from_file(p)
    assert wf.next_from("init") == ["build"]


# ---------------------------------------------------------------
# 条件边
# ---------------------------------------------------------------

def test_conditional_edge_success() -> None:
    wf = Workflow(CONDITIONAL_WF)
    assert wf.next_from("test", exit_code=0) == ["deploy"]


def test_conditional_edge_failure() -> None:
    wf = Workflow(CONDITIONAL_WF)
    assert wf.next_from("test", exit_code=1) == ["revert"]


def test_conditional_edge_unknown_code_goes_nowhere() -> None:
    wf = Workflow(CONDITIONAL_WF)
    assert wf.next_from("test", exit_code=2) == []


# ---------------------------------------------------------------
# on_failure 边
# ---------------------------------------------------------------

def test_on_failure_only_triggers_on_error() -> None:
    wf = Workflow(FAILURE_BRANCH_WF)
    # exit_code=0 → 只有无条件边 review
    assert wf.next_from("verify", exit_code=0) == ["review"]


def test_on_failure_with_error() -> None:
    wf = Workflow(FAILURE_BRANCH_WF)
    # exit_code=1 → 无条件边 review + on_failure 边 retry
    assert wf.next_from("verify", exit_code=1) == ["review", "retry"]


# ---------------------------------------------------------------
# 校验
# ---------------------------------------------------------------

def test_validate_valid_workflow() -> None:
    wf = Workflow(SIMPLE_WF)
    assert wf.validate() == []


def test_validate_missing_start_node() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "missing",
        "nodes": {"a": {"type": "script"}},
        "edges": [],
    })
    errors = wf.validate()
    assert any("start 节点" in e for e in errors)


def test_validate_invalid_edge_from() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {"a": {"type": "script"}},
        "edges": [{"from": "b", "to": "a"}],
    })
    errors = wf.validate()
    assert any("from='b'" in e for e in errors)


def test_validate_invalid_edge_to() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {"a": {"type": "script"}},
        "edges": [{"from": "a", "to": "missing"}],
    })
    errors = wf.validate()
    assert any("to='missing'" in e for e in errors)


def test_validate_unreachable_nodes() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {
            "a": {"type": "script"},
            "b": {"type": "script"},
            "c": {"type": "script"},
        },
        "edges": [
            {"from": "a", "to": "b"},
        ],
    })
    errors = wf.validate()
    assert any("不可达" in e for e in errors)
    assert any("c" in e for e in errors)


def test_validate_cycle_detection() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {
            "a": {"type": "script"},
            "b": {"type": "script"},
            "c": {"type": "script"},
        },
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
            {"from": "c", "to": "a"},
        ],
    })
    errors = wf.validate()
    assert any("环路" in e for e in errors)


def test_validate_self_loop_detected() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {"a": {"type": "script"}},
        "edges": [{"from": "a", "to": "a"}],
    })
    errors = wf.validate()
    assert any("环路" in e for e in errors)


def test_validate_foreach_missing_items() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "loop",
        "nodes": {
            "loop": {"type": "foreach", "template": "task"},
            "task": {"type": "script"},
        },
        "edges": [{"from": "loop", "to": "task"}],
    })
    errors = wf.validate()
    assert any("'items'" in e for e in errors)


def test_validate_foreach_missing_template() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "loop",
        "nodes": {
            "loop": {"type": "foreach", "items": "$tasks"},
            "task": {"type": "script"},
        },
        "edges": [{"from": "loop", "to": "task"}],
    })
    errors = wf.validate()
    assert any("'template'" in e for e in errors)


def test_validate_invalid_node_type() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "a",
        "nodes": {"a": {"type": "bogus"}},
        "edges": [],
    })
    errors = wf.validate()
    assert any("bogus" in e for e in errors)


def test_validate_no_errors_valid_types() -> None:
    wf = Workflow({
        "version": "1.0",
        "start": "start",
        "nodes": {
            "start": {"type": "script"},
            "approve": {"type": "human_approval"},
            "skill_node": {"type": "skill"},
            "loop": {"type": "foreach", "items": "$x", "template": "t"},
            "sub": {"type": "subgraph"},
        },
        "edges": [
            {"from": "start", "to": "approve"},
            {"from": "approve", "to": "skill_node"},
            {"from": "skill_node", "to": "loop"},
            {"from": "loop", "to": "sub"},
        ],
    })
    errors = wf.validate()
    assert errors == []


# ---------------------------------------------------------------
# to_dict 序列化
# ---------------------------------------------------------------

def test_to_dict_roundtrip() -> None:
    wf = Workflow(SIMPLE_WF)
    d = wf.to_dict()
    assert d["version"] == "1.0"
    assert d["start"] == "init"
    assert len(d["nodes"]) == 4
    assert len(d["edges"]) == 3


# ---------------------------------------------------------------
# 真实 AISE workflow.json
# ---------------------------------------------------------------

def test_aise_workflow_validates() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)
    errors = wf.validate()
    assert errors == [], f"真实 workflow.json 校验失败: {errors}"


def test_aise_workflow_full_traversal() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)

    # 正常流程遍历
    path = []
    current = wf.start_node()
    while current:
        path.append(current)
        next_nodes = wf.next_from(current, exit_code=0)
        current = next_nodes[0] if next_nodes else None

    expected = [
        "env_init", "brainstorm", "plan_mode", "run_init", "planning",
        "task_loop", "verify", "review", "fuse", "sediment", "dashboard",
    ]
    assert path == expected, f"正常流程路径:\n  期望: {expected}\n  实际: {path}"


def test_aise_workflow_verify_failure_retries() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)

    # verify 失败（硬门禁）→ 只回 task_loop 重试，不进软门禁 review
    next_on_fail = wf.next_from("verify", exit_code=1)
    assert next_on_fail == ["task_loop"], \
        "verify 失败应只回 task_loop（软门禁 review 不该在失败路径触发）"


def test_aise_workflow_fuse_exit_0_to_sediment() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)
    assert wf.next_from("fuse", exit_code=0) == ["sediment"]


def test_aise_workflow_fuse_exit_1_to_task_loop() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)
    assert wf.next_from("fuse", exit_code=1) == ["task_loop"]


def test_aise_workflow_has_11_nodes() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)
    assert len(wf.all_nodes()) == 11


def test_aise_workflow_node_types() -> None:
    wf_path = Path(__file__).resolve().parent.parent / ".aise" / "workflow.json"
    wf = Workflow.from_file(wf_path)
    types = {nid: nd["type"] for nid, nd in wf.nodes.items()}
    assert types["env_init"] == "script"
    assert types["brainstorm"] == "skill"
    assert types["plan_mode"] == "human_approval"
    assert types["task_loop"] == "foreach"
    assert types["review"] == "skill"


# ---------------------------------------------------------------
# CLI 集成测试
# ---------------------------------------------------------------

def test_cli_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "aise_workflow.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--validate" in result.stdout


def test_cli_validate(tmp_path: Path) -> None:
    import subprocess

    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps(SIMPLE_WF), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "aise_workflow.py"),
         "--workflow", str(wf_path), "--validate"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "校验通过" in result.stdout


def test_cli_list(tmp_path: Path) -> None:
    import subprocess

    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps(SIMPLE_WF), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "aise_workflow.py"),
         "--workflow", str(wf_path), "--list"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "init" in result.stdout


def test_cli_next(tmp_path: Path) -> None:
    import subprocess

    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps(SIMPLE_WF), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "aise_workflow.py"),
         "--workflow", str(wf_path), "--from", "init", "--exit-code", "0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["next"] == ["build"]


def test_cli_validate_with_errors(tmp_path: Path) -> None:
    import subprocess

    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps({
        "version": "1.0",
        "start": "missing",
        "nodes": {},
        "edges": [{"from": "a", "to": "b"}],
    }), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "aise_workflow.py"),
         "--workflow", str(wf_path), "--validate"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "校验失败" in result.stderr
