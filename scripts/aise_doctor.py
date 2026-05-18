#!/usr/bin/env python3
"""AISE Doctor — 一键自检 AISE 运行环境（v3.4 P2-1）

用户体验设计：永远不抛异常，缺什么列什么 + 平台特定安装命令。

退出码：
  0 = 全 ok（含 warn）
  1 = 仅 optional 缺失（pipe 工具可选时）
  2 = 关键缺失（Python 版本 / AISE 内部模块 / git / stdio 编码）

用法：
  python aise_doctor.py            # 默认 markdown 报告 + 友好提示
  python aise_doctor.py --json     # 机器可读 JSON
  python aise_doctor.py --strict   # 任何 fail 都视为 fatal exit 2
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List

# 让 lib.* 可 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_PYTHON = (3, 10)
ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


@dataclass
class Check:
    category: str       # python / aise_internal / git / stdio_encoding / pipe_tools / project
    name: str
    status: str         # ok / warn / fail
    detail: str = ""
    install_hint: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# ----------------------------- 各类 check -----------------------------


def check_python() -> List[Check]:
    vinfo = sys.version_info
    if (vinfo.major, vinfo.minor) >= MIN_PYTHON:
        st = "ok"
        detail = f"Python {vinfo.major}.{vinfo.minor}.{vinfo.micro} ≥ {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    else:
        st = "fail"
        detail = (f"Python {vinfo.major}.{vinfo.minor} 低于最低 "
                  f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
    return [Check("python", "Python 版本", st, detail,
                  install_hint="升级到 Python 3.10+：https://www.python.org/downloads/" if st == "fail" else "",
                  extra={"version": f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"})]


def check_aise_internal() -> List[Check]:
    """关键 lib 模块可 import。"""
    out: List[Check] = []
    modules = [
        ("lib.event_runner", "PIPE_DEFS + preflight + defense"),
        ("lib.lock", "跨平台 mkdir 锁 + Windows pid"),
        ("lib.target_cover", "cross-kind targetCovers"),
        ("lib.evidence", "evidence 签收链"),
        ("lib.snapshot", "plan.snapshot 防篡改"),
        ("lib.preflight", "通用工具预检"),
        ("lib.surefire_collector", "Surefire/Failsafe XML 收集"),
    ]
    for mod_name, purpose in modules:
        try:
            __import__(mod_name)
            out.append(Check("aise_internal", mod_name, "ok",
                             f"可 import — {purpose}"))
        except Exception as e:  # noqa: BLE001
            out.append(Check("aise_internal", mod_name, "fail",
                             f"import 失败: {e}",
                             install_hint="检查 scripts/ 与 scripts/lib/ 是否完整；"
                                         "重装插件可恢复"))
    return out


def check_git() -> List[Check]:
    bin_path = shutil.which("git")
    if not bin_path:
        return [Check("git", "git 命令", "fail",
                      "git 未在 PATH 上",
                      install_hint="macOS: xcode-select --install\n"
                                  "Linux: apt install git\n"
                                  "Windows: winget install Git.Git")]
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5)
        version = r.stdout.strip()
    except Exception:  # noqa: BLE001
        version = "未知"
    return [Check("git", "git 命令", "ok", f"{version}（{bin_path}）")]


def check_stdio_encoding() -> List[Check]:
    """检测当前 stdio 是否是 UTF-8。Windows 默认 cp1252 会让中文 stderr 出问题。"""
    checks: List[Check] = []

    pythonutf8 = os.environ.get("PYTHONUTF8", "")
    if pythonutf8 == "1":
        checks.append(Check("stdio_encoding", "PYTHONUTF8 环境变量",
                            "ok", "PYTHONUTF8=1（PEP 540 UTF-8 模式）"))
    else:
        checks.append(Check("stdio_encoding", "PYTHONUTF8 环境变量",
                            "warn", "未设置（建议显式启用 PEP 540 UTF-8 模式）",
                            install_hint=(
                                "macOS/Linux: export PYTHONUTF8=1\n"
                                "Windows PowerShell: $env:PYTHONUTF8=\"1\"\n"
                                "或 GitHub Actions yml 顶级 env: PYTHONUTF8: \"1\""
                            )))

    out_enc = (sys.stdout.encoding or "").lower()
    if "utf" in out_enc:
        checks.append(Check("stdio_encoding", "sys.stdout.encoding",
                            "ok", f"{out_enc}"))
    else:
        checks.append(Check("stdio_encoding", "sys.stdout.encoding",
                            "warn" if sys.platform != "win32" else "fail",
                            f"{out_enc!r}（非 UTF-8，Windows 中文 stderr 会乱码）",
                            install_hint="设 PYTHONUTF8=1 或 PYTHONIOENCODING=utf-8"))
    return checks


def check_pipe_tools() -> List[Check]:
    """复用 lib.event_runner.preflight_pipe 检查每个 pipe。"""
    out: List[Check] = []
    try:
        from lib import event_runner as er
    except Exception as e:  # noqa: BLE001
        return [Check("pipe_tools", "PIPE_DEFS 不可用", "fail",
                      f"event_runner import 失败: {e}")]

    for pipe_name in sorted(er.PIPE_DEFS.keys()):
        ok, info = er.preflight_pipe(pipe_name)
        if ok:
            out.append(Check(
                "pipe_tools", pipe_name, "ok",
                f"{info['bin']} → {info['found']} (via {info.get('via', 'path')})",
            ))
        else:
            if info.get("code") == "pipe_tool_missing":
                out.append(Check(
                    "pipe_tools", pipe_name, "fail",
                    f"工具 {info['bin']} 未在 PATH 上",
                    install_hint=info.get("install_hint", ""),
                    extra={"platform": info.get("platform", ""),
                           "purpose": info.get("purpose", "")},
                ))
            else:
                out.append(Check("pipe_tools", pipe_name, "fail",
                                 f"未知错误: {info}"))
    return out


def check_project(project_root: Path) -> List[Check]:
    """可选项目级检查：当 project_root 含 .aise/plan.json 时验证。"""
    out: List[Check] = []
    plan_json = project_root / ".aise" / "plan.json"
    if not plan_json.exists():
        return out  # 非 AISE 项目，跳过

    try:
        plan = json.loads(plan_json.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("project", "plan.json", "fail",
                         f"JSON 解析失败: {e}"))
        return out

    try:
        from aise_run_init import validate_plan
        errors = validate_plan(plan)
    except Exception as e:  # noqa: BLE001
        out.append(Check("project", "plan.json schema", "warn",
                         f"validate_plan 不可用: {e}"))
        return out

    if errors:
        out.append(Check(
            "project", "plan.json schema", "fail",
            f"{len(errors)} 项违规",
            extra={"errors": errors[:10]},  # 限 10 项防爆屏
        ))
    else:
        out.append(Check("project", "plan.json schema", "ok",
                         f"{len(plan.get('tasks', []))} 个 task 校验通过"))
    return out


# ----------------------------- 输出 -----------------------------


def render_markdown(
    checks: List[Check],
    summary: Dict[str, Any],
    region_info_dict: Dict[str, Any] | None = None,
    mirrors: Dict[str, Dict[str, Any]] | None = None,
) -> str:
    lines = ["# AISE Doctor 报告\n"]
    # 按 category 分组
    by_cat: Dict[str, List[Check]] = {}
    for c in checks:
        by_cat.setdefault(c.category, []).append(c)

    CAT_LABEL = {
        "python": "Python 运行时",
        "aise_internal": "AISE 内部模块",
        "git": "git 工具",
        "stdio_encoding": "stdio 编码",
        "pipe_tools": "Pipe Runner 工具链",
        "project": "项目（可选）",
    }
    for cat in ["python", "aise_internal", "git", "stdio_encoding", "pipe_tools", "project"]:
        if cat not in by_cat:
            continue
        lines.append(f"\n## {CAT_LABEL.get(cat, cat)}\n")
        for c in by_cat[cat]:
            lines.append(f"- {ICON[c.status]} **{c.name}** — {c.detail}")
            if c.install_hint and c.status != "ok":
                hint = c.install_hint.replace("\n", "\n      ")
                lines.append(f"    - 修复：")
                lines.append(f"      ```")
                lines.append(f"      {hint}")
                lines.append(f"      ```")

    # 镜像建议章节（仅 cn region 显示，避免噪声）
    if region_info_dict and mirrors and region_info_dict.get("detected") == "cn":
        lines.append("\n## 🌏 镜像建议（CN region 检测到）\n")
        lines.append(f"- region 源：`{region_info_dict.get('source')}`")
        if region_info_dict.get("timezone"):
            lines.append(f"- 时区：`{region_info_dict.get('timezone')}`")
        lines.append("")
        lines.append("以下镜像可加速 brew/maven/pip/npm/cargo 下载（焦小糖 Spike-2 实测 aliyun maven 可用）：\n")
        for tool, cfg in mirrors.items():
            if not cfg.get("url"):
                continue
            lines.append(f"### {tool}")
            lines.append(f"- URL: `{cfg['url']}`")
            if cfg.get("file_path"):
                lines.append(f"- 配置位置: `{cfg['file_path']}`")
            if cfg.get("doc"):
                lines.append(f"- 文档: {cfg['doc']}")
            cmd = cfg.get("setup_command", "").strip()
            if cmd:
                lines.append(f"- 启用命令：")
                lines.append("  ```")
                for line in cmd.splitlines():
                    lines.append(f"  {line}")
                lines.append("  ```")
            lines.append("")
        lines.append("**注意**：AISE 不会自动改用户镜像配置（敏感操作），仅提示。\n")

    lines.append("\n## 总结\n")
    lines.append(f"- 全部检查：{summary['total']}")
    lines.append(f"- ✅ ok: {summary['ok']}")
    lines.append(f"- ⚠️  warn: {summary['warn']}")
    lines.append(f"- ❌ fail: {summary['fail']}")
    lines.append(f"- exit code: **{summary['exit_code']}**")
    if region_info_dict:
        lines.append(f"- region: {region_info_dict.get('detected')}（{region_info_dict.get('source')}）")
    if summary.get("strict"):
        lines.append("- 模式：strict（任何 fail 都视为 fatal）")
    return "\n".join(lines) + "\n"


# ----------------------------- main -----------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="aise_doctor",
        description="AISE Doctor — 一键自检运行环境",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 markdown")
    parser.add_argument("--strict", action="store_true",
                        help="任何 fail（含 optional）都视为 fatal exit 2")
    parser.add_argument("--project-root", default=None,
                        help="项目根目录，存在 .aise/plan.json 时做项目级 check")
    parser.add_argument("--region", default=None, choices=["cn", "us", "global"],
                        help="手动指定 region（覆盖 AISE_REGION env + timezone 自动探测）")
    parser.add_argument("--check-versions", action="store_true",
                        help="额外跑工具版本检查，与 tool-compatibility-matrix 对比")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()

    # region 探测（--region 优先，否则走 region_detect）
    region_info_dict: Dict[str, Any] = {}
    mirrors_dict: Dict[str, Dict[str, Any]] = {}
    try:
        from lib import region_detect as rd
        from lib import mirror_config as mc
        if args.region:
            region_info_dict = {
                "detected": args.region,
                "source": "cli_flag",
                "env_AISE_REGION": os.environ.get("AISE_REGION") or None,
                "timezone": rd._get_timezone_name() or None,
            }
        else:
            region_info_dict = rd.region_info()
        mirrors_dict = mc.get_mirrors(region_info_dict["detected"])
    except Exception as e:  # noqa: BLE001
        # 不让 region detect 失败阻塞 doctor 主体
        region_info_dict = {"detected": "global", "source": "detect_error", "error": str(e)}

    checks: List[Check] = []
    checks.extend(check_python())
    checks.extend(check_aise_internal())
    checks.extend(check_git())
    checks.extend(check_stdio_encoding())
    checks.extend(check_pipe_tools())
    checks.extend(check_project(project_root))

    # v3.5 P1-2: 可选版本检查
    version_checks: List[Dict[str, Any]] = []
    if args.check_versions:
        try:
            from lib.version_check import check_all_versions
            version_checks = check_all_versions()
        except Exception as e:  # noqa: BLE001
            version_checks = [{"tool": "(version_check)", "status": "fail",
                               "reason": f"import failed: {e}"}]

    n_ok = sum(1 for c in checks if c.status == "ok")
    n_warn = sum(1 for c in checks if c.status == "warn")
    n_fail = sum(1 for c in checks if c.status == "fail")

    # 退出码策略：
    #   strict 模式：任何 fail 或 warn → 2
    #   非 strict：
    #     - 关键 fail（python / aise_internal / git / stdio_encoding 含 fail） → 2
    #     - 仅 pipe_tools / project fail → 1（用户按需装）
    #     - 全 ok 或 warn → 0
    if args.strict:
        exit_code = 2 if (n_fail > 0 or n_warn > 0) else 0
    else:
        critical_fail = any(
            c.status == "fail" and c.category in {"python", "aise_internal", "git", "stdio_encoding"}
            for c in checks
        )
        if critical_fail:
            exit_code = 2
        elif n_fail > 0:
            exit_code = 1
        else:
            exit_code = 0

    summary = {
        "total": len(checks),
        "ok": n_ok,
        "warn": n_warn,
        "fail": n_fail,
        "exit_code": exit_code,
        "strict": args.strict,
        "platform": sys.platform,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

    if args.json:
        # 仅 cn region 输出有效的 mirror 推荐（global/us 为空 url，过滤）
        mirrors_for_json = {
            t: cfg for t, cfg in mirrors_dict.items() if cfg.get("url")
        } if region_info_dict.get("detected") == "cn" else {}
        print(json.dumps(
            {
                "checks": [asdict(c) for c in checks],
                "summary": summary,
                "region": region_info_dict,
                "mirrors": mirrors_for_json,
                "version_checks": version_checks,
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        md = render_markdown(checks, summary, region_info_dict, mirrors_dict)
        if version_checks:
            md += _render_version_section(version_checks)
        print(md)

    return exit_code


def _render_version_section(version_checks: List[Dict[str, Any]]) -> str:
    """渲染版本检查 markdown 章节."""
    icon_map = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏸️"}
    lines = ["\n## 🔢 版本检查（与 tool-compatibility-matrix.md 对比）\n"]
    for vc in version_checks:
        icon = icon_map.get(vc["status"], "?")
        if vc["status"] in ("ok", "warn"):
            line = (f"- {icon} **{vc['tool']}** — actual `{vc['actual']}` / "
                    f"min `{vc['min_version']}`")
        elif vc["status"] == "skip":
            line = f"- {icon} **{vc['tool']}** — 未装（min `{vc.get('min_version', '?')}`），见 pipe_tools 检查项"
        else:
            line = f"- {icon} **{vc['tool']}** — {vc.get('reason', '检查失败')}"
        if vc.get("purpose"):
            line += f"  *（{vc['purpose']}）*"
        lines.append(line)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
