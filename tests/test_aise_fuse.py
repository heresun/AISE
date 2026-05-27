"""aise_fuse.py 单元测试 — 熔断判断逻辑"""
import json
import pytest
from pathlib import Path

from scripts.aise_fuse import main as fuse_main


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestFuse:
    def test_no_error_log_returns_0(self, tmp_path: Path):
        (tmp_path / ".aise").mkdir()
        result = fuse_main_custom(tmp_path, 2, 200000, 15)
        assert result == 0

    def test_empty_log_returns_0(self, tmp_path: Path):
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", [])
        result = fuse_main_custom(tmp_path, 2, 200000, 15)
        assert result == 0

    def test_repeat_errors_triggers_fuse(self, tmp_path: Path):
        entries = [
            {"is_error": True, "error_type": "test_fail", "file": "a.py", "est_tokens": 100}
            for _ in range(3)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 2, 200000, 15)
        assert result == 2

    def test_below_repeat_threshold_does_not_trigger(self, tmp_path: Path):
        entries = [
            {"is_error": True, "error_type": "test_fail", "file": "a.py", "est_tokens": 100}
            for _ in range(1)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 2, 200000, 15)
        assert result == 0

    def test_token_budget_exceeded_triggers_fuse(self, tmp_path: Path):
        entries = [
            {"is_error": False, "error_type": None, "file": "a.py", "est_tokens": 50000}
            for _ in range(5)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 2, 100000, 15)
        assert result == 2

    def test_blast_radius_exceeded_triggers_fuse(self, tmp_path: Path):
        entries = [
            {"is_error": True, "error_type": None, "file": f"file_{i}.py", "est_tokens": 10}
            for i in range(20)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 99, 999999, 15)
        assert result == 2

    def test_no_error_entries_returns_0(self, tmp_path: Path):
        entries = [
            {"is_error": False, "error_type": None, "file": "a.py", "est_tokens": 10}
            for _ in range(10)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 2, 200000, 15)
        assert result == 0

    def test_snapshot_skip_flag(self, tmp_path: Path):
        entries = [
            {"is_error": True, "error_type": "test_fail", "file": "a.py", "est_tokens": 100}
            for _ in range(3)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 2, 200000, 15, skip_snapshot=True)
        assert result == 2

    def test_frequent_error_type_switch_triggers(self, tmp_path: Path):
        types = ["test_fail", "type_error", "lint_fail", "compile_fail"]
        entries = [
            {"is_error": True, "error_type": types[i % len(types)], "file": "a.py", "est_tokens": 10}
            for i in range(10)
        ]
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", entries)
        result = fuse_main_custom(tmp_path, 99, 999999, 99)
        assert result == 2


def fuse_main_custom(project_root: Path, repeat_th: int, token_budget: int,
                     blast_radius: int, skip_snapshot: bool = False) -> int:
    """Call main() with custom args, bypassing argparse."""
    import sys
    sys.argv = [
        "aise_fuse.py",
        "--project-root", str(project_root),
        "--repeat-threshold", str(repeat_th),
        "--token-budget", str(token_budget),
        "--blast-radius", str(blast_radius),
    ]
    if skip_snapshot:
        sys.argv.append("--skip-snapshot-check")
    return fuse_main()
