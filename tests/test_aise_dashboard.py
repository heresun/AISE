"""aise_dashboard.py 单元测试 — 健康度报表生成"""
import json
import pytest
from pathlib import Path


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )


class TestDashboard:
    def test_no_metrics_returns_0(self, tmp_path: Path, capsys):
        import sys
        from scripts.aise_dashboard import main
        (tmp_path / ".aise").mkdir()
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        sys.argv = [
            "aise_dashboard.py",
            "--project-root", str(tmp_path),
            "--output-dir", str(report_dir),
            "--skip-snapshot-check",
        ]
        result = main()
        assert result == 0
        captured = capsys.readouterr()
        assert "无 metrics 数据" in captured.out

    def test_generates_report_with_metrics(self, tmp_path: Path):
        import sys
        from scripts.aise_dashboard import main
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        metrics = [
            {"phase": "verify", "pass": True},
            {"phase": "verify", "pass": True},
            {"phase": "verify", "pass": False},
            {"phase": "fuse", "triggered": False},
        ]
        _write_jsonl(tmp_path / ".aise" / "metrics.jsonl", metrics)
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", [
            {"is_error": True, "error_type": "test_fail", "file": "a.py", "est_tokens": 100},
        ])
        sys.argv = [
            "aise_dashboard.py",
            "--project-root", str(tmp_path),
            "--output-dir", str(report_dir),
            "--skip-snapshot-check",
        ]
        result = main()
        assert result == 0
        reports = list(report_dir.glob("*-aise-health.md"))
        assert len(reports) == 1
        content = reports[0].read_text(encoding="utf-8")
        assert "健康度" in content
        assert "verify" in content

    def test_high_health_score(self, tmp_path: Path):
        import sys
        from scripts.aise_dashboard import main
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        _write_jsonl(tmp_path / ".aise" / "metrics.jsonl", [
            {"phase": "verify", "pass": True} for _ in range(10)
        ])
        (tmp_path / ".aise" / "patterns").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".aise" / "patterns" / "p1.md").write_text("# test")
        (tmp_path / ".aise" / "patterns" / "p2.md").write_text("# test")
        (tmp_path / ".aise" / "patterns" / "p3.md").write_text("# test")
        sys.argv = [
            "aise_dashboard.py",
            "--project-root", str(tmp_path),
            "--output-dir", str(report_dir),
            "--skip-snapshot-check",
        ]
        result = main()
        assert result == 0

    def test_low_token_triggers_high_cost_score(self, tmp_path: Path):
        import sys
        from scripts.aise_dashboard import main
        report_dir = tmp_path / "reports"
        report_dir.mkdir()
        _write_jsonl(tmp_path / ".aise" / "metrics.jsonl", [
            {"phase": "verify", "pass": True},
        ])
        _write_jsonl(tmp_path / ".aise" / "error_patterns.jsonl", [
            {"is_error": False, "error_type": None, "file": "x.py", "est_tokens": 100},
        ])
        sys.argv = [
            "aise_dashboard.py",
            "--project-root", str(tmp_path),
            "--output-dir", str(report_dir),
            "--skip-snapshot-check",
        ]
        main()
        reports = list(report_dir.glob("*-aise-health.md"))
        content = reports[0].read_text(encoding="utf-8")
        assert "30 / 30" in content
