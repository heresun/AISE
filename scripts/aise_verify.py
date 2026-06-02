#!/usr/bin/env python3
"""AISE 客观验证门禁（优化①）— 跨平台 Python 版

退出码：
  0   = 通过
  1   = 业务验证失败（测试/lint/typecheck 红）
  2   = 状态异常（plan snapshot 不存在/被篡改）
  127 = 环境异常（必需工具不在 PATH）

v1.1 新增（方案 A）：
  - 启动时 plan.snapshot.json 防篡改校验
  - 每个 runner 跑前 preflight 工具存在性
  - 每个 runner 跑后收集 evidence artifact（JUnit XML + stdout 转储）
  - 写 .aise/runs/<run_id>/evidence.jsonl 供下游 gate 重校验
  - --verify-evidence 模式：对最近一次 run 的 evidence 全量重校验，
    用于审查阶段 / 跨 session 续跑时确认证据未被篡改
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 让 scripts/lib 可 import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import anchor as anchor_lib  # noqa: E402
from lib import evidence as ev_lib  # noqa: E402
from lib import preflight as pf_lib  # noqa: E402
from lib import snapshot as snap_lib  # noqa: E402


def _now_ms() -> int:
    return int(time.time() * 1000)


def run_step(name: str, cmd: str, cwd: Path, timeout: int = 300, stdout_dump: Path | None = None):
    """执行命令；返回 (ok, duration_sec, window_start_ms, window_end_ms)"""
    print(f"[AISE-verify] >>> {name}: {cmd}")
    window_start = _now_ms()
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.time() - t0
        window_end = _now_ms()
        ok = result.returncode == 0

        # 落盘 stdout/stderr 作为 evidence
        if stdout_dump is not None:
            stdout_dump.parent.mkdir(parents=True, exist_ok=True)
            stdout_dump.write_text(
                f"# cmd: {cmd}\n# exit: {result.returncode}\n# duration_sec: {duration:.2f}\n"
                f"\n===== STDOUT =====\n{result.stdout or ''}\n"
                f"===== STDERR =====\n{result.stderr or ''}\n",
                encoding="utf-8",
            )

        if not ok:
            tail = (result.stderr or "").splitlines()[-30:]
            print(f"[AISE-verify] FAIL: {name}")
            for line in tail:
                print(f"  {line}")
        return ok, duration, window_start, window_end
    except subprocess.TimeoutExpired:
        window_end = _now_ms()
        print(f"[AISE-verify] TIMEOUT: {name}")
        if stdout_dump is not None:
            stdout_dump.parent.mkdir(parents=True, exist_ok=True)
            stdout_dump.write_text(f"# cmd: {cmd}\n# TIMEOUT after {timeout}s\n", encoding="utf-8")
        return False, float(timeout), window_start, window_end
    except Exception as exc:  # noqa: BLE001
        window_end = _now_ms()
        print(f"[AISE-verify] ERROR: {exc}")
        return False, 0.0, window_start, window_end


def _collect_junit_xmls(report_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in report_dirs:
        if d.exists() and d.is_dir():
            files.extend(sorted(d.glob("*.xml")))
    return files


def detect_and_run(project_root: Path, run_id: str):
    is_windows = platform.system() == "Windows"
    gradle_cmd = "gradlew.bat" if is_windows else "./gradlew"

    run_dir = project_root / ".aise" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_root = run_dir / "stdout"

    results = []
    all_evidences: list[ev_lib.Evidence] = []
    all_ok = True

    def add_evidence_from(files: list[Path], runner: str, ws: int, we: int, src: str, ok: bool):
        for fp in files:
            ev = ev_lib.collect_artifact(fp, runner, ws, we, src, ok, project_root)
            if ev is not None:
                all_evidences.append(ev)

    def maybe_add_dump(dump: Path, runner: str, ws: int, we: int, ok: bool):
        if dump.exists():
            ev = ev_lib.collect_artifact(dump, runner, ws, we, "stdout_dump", ok, project_root)
            if ev is not None:
                all_evidences.append(ev)

    def record(name: str, ok: bool, duration: float):
        results.append({"name": name, "pass": ok, "sec": round(duration, 1)})

    # ---- Maven ----
    if (project_root / "pom.xml").exists():
        pf_lib.preflight_or_exit("mvn", project_root=project_root)
        dump = stdout_root / "maven_test.log"
        ok, dur, ws, we = run_step("Maven Test", "mvn test -q -DskipITs", project_root, stdout_dump=dump)
        record("Maven Test", ok, dur)
        all_ok = all_ok and ok
        maybe_add_dump(dump, "Maven Test", ws, we, ok)
        add_evidence_from(
            _collect_junit_xmls(
                [project_root / "target" / "surefire-reports", project_root / "target" / "failsafe-reports"]
            ),
            "Maven Test",
            ws,
            we,
            "junit_xml",
            ok,
        )

    # ---- Gradle ----
    if (project_root / "build.gradle").exists() or (project_root / "build.gradle.kts").exists():
        pf_lib.preflight_or_exit("gradle", project_root=project_root)
        dump = stdout_root / "gradle_test.log"
        ok, dur, ws, we = run_step("Gradle Test", f"{gradle_cmd} test --console=plain", project_root, stdout_dump=dump)
        record("Gradle Test", ok, dur)
        all_ok = all_ok and ok
        maybe_add_dump(dump, "Gradle Test", ws, we, ok)
        # gradle 默认 build/test-results/test/*.xml
        add_evidence_from(
            _collect_junit_xmls([project_root / "build" / "test-results" / "test"]),
            "Gradle Test",
            ws,
            we,
            "junit_xml",
            ok,
        )

    # ---- npm ----
    pkg_path = project_root / "package.json"
    if pkg_path.exists():
        pf_lib.preflight_or_exit("npm", project_root=project_root)
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {}) or {}
            for script in ("test", "lint", "typecheck"):
                if script not in scripts:
                    continue
                cmd = "npm test --silent" if script == "test" else f"npm run {script} --silent"
                dump = stdout_root / f"npm_{script}.log"
                ok, dur, ws, we = run_step(f"npm {script}", cmd, project_root, stdout_dump=dump)
                record(f"npm {script}", ok, dur)
                all_ok = all_ok and ok
                maybe_add_dump(dump, f"npm {script}", ws, we, ok)
        except Exception as exc:  # noqa: BLE001
            print(f"[AISE-verify] package.json 解析失败: {exc}")

    # ---- Python ----
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        pytest_bin = pf_lib.preflight_or_exit("pytest", project_root=project_root)
        # 让 pytest 产出 junit xml 作为强证据
        junit_path = run_dir / "pytest-junit.xml"
        pytest_invocation = pytest_bin if "python" in pytest_bin else "pytest"
        dump = stdout_root / "pytest.log"
        ok, dur, ws, we = run_step(
            "pytest",
            f'{pytest_invocation} -q --junitxml="{junit_path}"',
            project_root,
            stdout_dump=dump,
        )
        record("pytest", ok, dur)
        all_ok = all_ok and ok
        maybe_add_dump(dump, "pytest", ws, we, ok)
        add_evidence_from([junit_path], "pytest", ws, we, "junit_xml", ok)

        # ruff 是可选的
        ruff_bin = pf_lib.preflight_or_exit("ruff", project_root=project_root)
        if ruff_bin:
            dump = stdout_root / "ruff.log"
            ok2, dur2, ws2, we2 = run_step("ruff", "ruff check .", project_root, stdout_dump=dump)
            record("ruff", ok2, dur2)
            all_ok = all_ok and ok2
            maybe_add_dump(dump, "ruff", ws2, we2, ok2)

    return all_ok, results, all_evidences


def _do_verify_evidence(project_root: Path) -> int:
    """--verify-evidence 模式：重新校验最近一次 run 的 evidence 链未被篡改"""
    latest = ev_lib.latest_run_dir(project_root)
    if latest is None:
        print("[AISE-verify] 没找到任何 .aise/runs/<run_id>/，无 evidence 可校验", file=sys.stderr)
        return 2
    evidence_path = latest / "evidence.jsonl"
    print(f"[AISE-verify] 重校验 evidence: {evidence_path}")
    ok, violations = ev_lib.verify_evidence(evidence_path, project_root)

    # 附加：内容外锚校验（#8，git hash-object 内容寻址；无 git/无 anchor 自动放行）
    if (latest / "anchor.json").exists():
        a_ok, a_violations = anchor_lib.verify_anchor(latest.name, project_root)
        real = [v for v in a_violations if v.get("code") != "anchor_skipped"]
        if a_ok and not real:
            print("[AISE-verify] 内容外锚校验通过（tamper-evident）")
        if real:
            ok = False
            violations = list(violations) + [{"anchor": v} for v in real]

    if ok:
        print("[AISE-verify] evidence 全部签收，未发现篡改")
        return 0
    print(f"[AISE-verify] evidence 校验失败：{len(violations)} 项违规")
    for v in violations:
        print(f"  - {v}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 客观验证")
    parser.add_argument("--project-root", default=None)
    parser.add_argument(
        "--verify-evidence",
        action="store_true",
        help="不跑测试，重新校验最近一次 run 的 evidence.jsonl",
    )
    parser.add_argument(
        "--skip-snapshot-check",
        action="store_true",
        help="跳过 plan.snapshot 防篡改校验（仅用于本地调试/CI 引导）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()

    # 启动门禁：snapshot 防篡改（除非显式 skip 或项目还没初始化）
    if not args.skip_snapshot_check:
        aise_dir = project_root / ".aise"
        if (aise_dir / "plan.snapshot.json").exists():
            snap_lib.require_snapshot(project_root, gate_name="verify")
        # 若 snapshot 不存在则跳过——尚未走完 /aise 步骤 2 的项目可裸跑 verify

    if args.verify_evidence:
        return _do_verify_evidence(project_root)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    start = time.time()

    all_ok, results, evidences = detect_and_run(project_root, run_id)

    total = time.time() - start
    print(f"\n[AISE-verify] === 汇总 (用时 {total:.1f}s) ===")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['name']} ({r['sec']}s)")

    # 写 evidence chain
    if evidences:
        ev_path = ev_lib.write_evidence(evidences, project_root, run_id=run_id)
        print(f"[AISE-verify] evidence 链 ({len(evidences)} 条) → {ev_path}")
        # 内容外锚（#8）：写入 .git/objects + 独立 ref，提高篡改成本 + 留痕；无 git 自动跳过
        anchor_result = anchor_lib.anchor_run(run_id, project_root)
        if anchor_result["status"] == "anchored":
            print(f"[AISE-verify] 内容外锚 {anchor_result['anchored']} 件 → ref {anchor_result['ref']}")

    aise_dir = project_root / ".aise"
    if aise_dir.exists():
        metrics_path = aise_dir / "metrics.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "phase": "verify",
            "run_id": run_id,
            "pass": all_ok,
            "duration_sec": round(total, 1),
            "steps": results,
            "evidence_count": len(evidences),
        }
        with metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not all_ok:
        print("[AISE-verify] 硬门禁未通过，请回到执行阶段修复")
        return 1

    print("[AISE-verify] 全部通过 — evidence 链已签收，下游可走 --verify-evidence 复核")
    return 0


if __name__ == "__main__":
    sys.exit(main())
