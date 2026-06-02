"""aise_sediment.py 单元测试 — patterns 知识沉淀"""
import pytest
from pathlib import Path


def test_safe_filename_replaces_special_chars():
    from scripts.aise_sediment import safe_filename
    assert safe_filename("hello world") == "hello-world"
    assert safe_filename("a/b:c") == "a_b_c"
    assert safe_filename('test"file*name') == "test_file_name"


def test_safe_filename_handles_unicode():
    from scripts.aise_sediment import safe_filename
    assert safe_filename("测试-模式") == "测试-模式"


def test_main_writes_project_pattern(tmp_path: Path, capsys):
    import sys
    from scripts.aise_sediment import main
    sys.argv = [
        "aise_sediment.py",
        "--project-root", str(tmp_path),
        "--title", "修复测试超时",
        "--body", "解决方法是增加 pytest timeout 参数。",
        "--tags", "test", "timeout",
    ]
    result = main()
    assert result == 0
    pattern_files = list((tmp_path / ".aise" / "patterns").glob("*.md"))
    assert len(pattern_files) == 1
    content = pattern_files[0].read_text(encoding="utf-8")
    assert "修复测试超时" in content
    assert "pytest timeout" in content
    assert "test" in content


def test_main_with_file_body(tmp_path: Path, capsys):
    import sys
    from scripts.aise_sediment import main
    body_file = tmp_path / "body.md"
    body_file.write_text("从文件读取的内容", encoding="utf-8")
    sys.argv = [
        "aise_sediment.py",
        "--project-root", str(tmp_path),
        "--title", "文件模式",
        "--body", f"@{body_file}",
        "--tags", "test",
    ]
    result = main()
    assert result == 0
    pattern_files = list((tmp_path / ".aise" / "patterns").glob("*.md"))
    assert len(pattern_files) == 1
    content = pattern_files[0].read_text(encoding="utf-8")
    assert "从文件读取的内容" in content


def test_main_with_global_flag(tmp_path: Path, monkeypatch, capsys):
    import sys
    from scripts.aise_sediment import main
    global_dir = tmp_path / ".claude" / "docs" / "patterns"
    monkeypatch.setattr("scripts.aise_sediment.Path.home", lambda: tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".claude" / "docs" / "patterns").mkdir(parents=True, exist_ok=True)
    sys.argv = [
        "aise_sediment.py",
        "--project-root", str(tmp_path),
        "--title", "全局模式",
        "--body", "全局内容",
        "--tags", "global",
        "--global",
    ]
    result = main()
    assert result == 0
    global_files = list(global_dir.glob("**/*全局模式*.md"))
    assert len(global_files) >= 1
