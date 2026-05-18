"""region_detect + mirror_config 单元测试（v3.4 P1-3）

策略：
  - 不做网络探测（DNS 延迟）；仅 timezone + env var
  - 不直接改用户配置（敏感）；仅提示
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib import region_detect as rd
from lib import mirror_config as mc


# ----------------------------- region_detect -----------------------------


def test_detect_region_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISE_REGION", "cn")
    assert rd.detect_region() == "cn"

    monkeypatch.setenv("AISE_REGION", "us")
    assert rd.detect_region() == "us"


def test_detect_region_invalid_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """AISE_REGION 设非法值时回落到 timezone/default."""
    monkeypatch.setenv("AISE_REGION", "totally-invalid")
    region = rd.detect_region()
    assert region in {"cn", "us", "global"}  # fallback 合法


def test_detect_region_cn_via_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISE_REGION", raising=False)
    monkeypatch.setattr(rd, "_get_timezone_name", lambda: "Asia/Shanghai")
    assert rd.detect_region() == "cn"


def test_detect_region_us_via_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISE_REGION", raising=False)
    monkeypatch.setattr(rd, "_get_timezone_name", lambda: "America/Los_Angeles")
    assert rd.detect_region() == "us"


def test_detect_region_unknown_timezone_falls_back_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AISE_REGION", raising=False)
    monkeypatch.setattr(rd, "_get_timezone_name", lambda: "Europe/Berlin")
    assert rd.detect_region() == "global"


def test_detect_region_no_timezone_falls_back_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AISE_REGION", raising=False)
    monkeypatch.setattr(rd, "_get_timezone_name", lambda: "")
    assert rd.detect_region() == "global"


def test_supported_regions_constant() -> None:
    assert "cn" in rd.SUPPORTED_REGIONS
    assert "us" in rd.SUPPORTED_REGIONS
    assert "global" in rd.SUPPORTED_REGIONS


# ----------------------------- mirror_config -----------------------------


def test_get_mirrors_for_cn_returns_5_tools() -> None:
    mirrors = mc.get_mirrors("cn")
    assert isinstance(mirrors, dict)
    expected = {"brew", "maven", "pip", "npm", "cargo"}
    assert expected.issubset(set(mirrors.keys())), \
        f"cn 镜像缺工具: {expected - set(mirrors.keys())}"


def test_get_mirrors_for_global_returns_no_override() -> None:
    """global region 不推荐 override，返回空 dict 或 default."""
    mirrors = mc.get_mirrors("global")
    # global 应该返回 {} 或所有 url 为 None / "default"
    if mirrors:
        for tool, cfg in mirrors.items():
            assert cfg.get("url") in (None, "", "default"), \
                f"global region 不应推荐 mirror: {tool}={cfg}"


def test_get_mirrors_for_cn_brew_uses_known_mirror() -> None:
    mirrors = mc.get_mirrors("cn")
    brew = mirrors["brew"]
    assert "url" in brew
    assert any(domain in brew["url"] for domain in
               ["ustc.edu.cn", "tuna.tsinghua.edu.cn", "aliyun.com", "tencent.com"])


def test_get_mirrors_for_cn_maven_uses_aliyun() -> None:
    mirrors = mc.get_mirrors("cn")
    mvn = mirrors["maven"]
    assert "aliyun.com" in mvn["url"]


def test_get_mirrors_for_cn_pip_uses_known_mirror() -> None:
    mirrors = mc.get_mirrors("cn")
    pip = mirrors["pip"]
    assert any(domain in pip["url"] for domain in
               ["aliyun.com", "tuna.tsinghua.edu.cn", "ustc.edu.cn", "tencent.com"])


def test_each_mirror_has_setup_command() -> None:
    """每个镜像配置必须有 setup_command 字段告诉用户怎么生效."""
    mirrors = mc.get_mirrors("cn")
    for tool, cfg in mirrors.items():
        if cfg.get("url"):  # 仅检查实际推荐 mirror 的工具
            assert "setup_command" in cfg, f"{tool} 缺 setup_command"
            assert cfg["setup_command"], f"{tool}.setup_command 为空"


def test_unknown_region_returns_global_or_empty() -> None:
    """不在 SUPPORTED_REGIONS 的 region 应安全返回 global 默认."""
    mirrors = mc.get_mirrors("mars")
    # 不抛异常，返回 {} 或 global config
    assert isinstance(mirrors, dict)


# ----------------------------- aise_doctor 集成 -----------------------------


def test_doctor_json_includes_region_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """aise_doctor --json 输出应含 region + mirror recommendations 字段."""
    import json, subprocess, sys

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DOCTOR = PROJECT_ROOT / "scripts" / "aise_doctor.py"

    env = os.environ.copy()
    env["AISE_REGION"] = "cn"  # 强制 CN
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(
        [sys.executable, str(DOCTOR), "--json"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    data = json.loads(r.stdout)
    assert "region" in data
    assert data["region"]["detected"] == "cn"
    assert "mirrors" in data
    assert "maven" in data["mirrors"]  # cn 至少应推荐 maven 镜像


def test_doctor_markdown_includes_mirror_section() -> None:
    """默认 markdown 输出当 region=cn 时应含"镜像建议"章节."""
    import subprocess, sys

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DOCTOR = PROJECT_ROOT / "scripts" / "aise_doctor.py"
    env = os.environ.copy()
    env["AISE_REGION"] = "cn"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(
        [sys.executable, str(DOCTOR)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    assert "镜像" in r.stdout or "mirror" in r.stdout.lower()
    assert "aliyun" in r.stdout.lower() or "ustc" in r.stdout.lower() or "tuna" in r.stdout.lower()


def test_doctor_no_mirror_section_when_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """region=global 时不推 mirror 章节（避免噪声）."""
    import subprocess, sys

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DOCTOR = PROJECT_ROOT / "scripts" / "aise_doctor.py"
    env = os.environ.copy()
    env["AISE_REGION"] = "global"
    env["PYTHONUTF8"] = "1"
    r = subprocess.run(
        [sys.executable, str(DOCTOR)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    # global region 应不展示 mirror 镜像（或显示"无需推荐"）
    # 我们用 markdown 中应不含具体国内镜像 URL 来判定
    assert "aliyun.com" not in r.stdout
