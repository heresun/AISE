"""docs/plan-schema.json 防漂移测试（#4 错误前移）

plan-schema.json 是给 LLM 看的机器可读约束（由 aise-planning-with-files skill 内嵌），
它必须与 aise_run_init.validate_plan 的真实校验规则保持单一事实源一致。

本测试钉住最易漂移的几个点：
  - pipe 枚举 == event_runner.PIPE_DEFS（新增 pipe 时两边必须同步）
  - 顶级 required 字段与 _validate_top_level 一致
  - task 级 required 字段与 _validate_one_task 一致
  - schema_version 锁定为 "1.0"

刻意不引入 validate_plan 并不强制的约束（例如 task_id 的 T-\\d{3} pattern），
避免「schema 比代码严」的虚假约束。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
SCHEMA_PATH = PROJECT_ROOT / "docs" / "plan-schema.json"

sys.path.insert(0, str(SCRIPTS))
from lib import event_runner as er  # noqa: E402


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _task_props(schema: dict) -> dict:
    return schema["properties"]["tasks"]["items"]["properties"]


def test_plan_schema_json_exists() -> None:
    assert SCHEMA_PATH.exists(), "docs/plan-schema.json 应存在（planning skill 内嵌约束源）"


def test_pipe_enum_matches_pipe_defs() -> None:
    schema = _load_schema()
    pipe_enum = _task_props(schema)["test_manifest"]["properties"]["pipe"]["enum"]
    assert set(pipe_enum) == set(er.PIPE_DEFS.keys()), \
        "plan-schema.json 的 pipe 枚举必须与 PIPE_DEFS 同步（新增 pipe 别忘了改 schema）"


def test_top_level_required_fields() -> None:
    schema = _load_schema()
    assert set(schema["required"]) == {"schema_version", "task_title", "tasks"}


def test_schema_version_locked_to_1_0() -> None:
    schema = _load_schema()
    assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_task_required_fields() -> None:
    schema = _load_schema()
    item = schema["properties"]["tasks"]["items"]
    assert set(item["required"]) == {"task_id", "title", "scope", "test_manifest"}


def test_scope_paths_required_and_non_empty() -> None:
    schema = _load_schema()
    scope = _task_props(schema)["scope"]
    assert "paths" in scope["required"]
    assert scope["properties"]["paths"]["minItems"] >= 1
