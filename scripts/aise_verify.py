#!/usr/bin/env python3
"""AISE 客观验证门禁（优化①）- 跨平台 Python 版

退出码：0 = 通过；1 = 验证失败；2 = 环境异常
"""
import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def run_step(name: str, cmd: str, cwd: Path, timeout: int = 300):
    t0 = time.time()
    print(f"[AISE-verify] >>> {name}: {cmd}")
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
        ok = result.returncode == 0
        if not ok:
            tail = (result.stderr or "").splitlines()[-30:]
            print(f"[AISE-verify] FAIL: {name}")
            for line in tail:
                print(f"  {line}")
        return ok, duration
    except subprocess.TimeoutExpired:
        print(f"[AISE-verify] TIMEOUT: {name}")
        return False, float(timeout)
    except Exception as exc:
        print(f"[AISE-verify] ERROR: {exc}")
        return False, 0.0


def detect_and_run(project_root: Path):
    is_windows = platform.system() == "Windows"
    gradle_cmd = "gradlew.bat" if is_windows else "./gradlew"

    results = []
    all_ok = True

    def record(name: str, ok: bool, duration: float):
        results.append({"name": name, "pass": ok, "sec": round(duration, 1)})

    if (project_root / "pom.xml").exists():
        ok, dur = run_step("Maven Test", "mvn test -q -DskipITs", project_root)
        record("Maven Test", ok, dur)
        all_ok = all_ok and ok

    if (project_root / "build.gradle").exists() or (project_root / "build.gradle.kts").exists():
        ok, dur = run_step("Gradle Test", f"{gradle_cmd} test --console=plain", project_root)
        record("Gradle Test", ok, dur)
        all_ok = all_ok and ok

    pkg_path = project_root / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {}) or {}
            for script in ("test", "lint", "typecheck"):
                if script not in scripts:
                    continue
                cmd = "npm test --silent" if script == "test" else f"npm run {script} --silent"
                ok, dur = run_step(f"npm {script}", cmd, project_root)
                record(f"npm {script}", ok, dur)
                all_ok = all_ok and ok
        except Exception as exc:
            print(f"[AISE-verify] package.json 解析失败: {exc}")

    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        ok, dur = run_step("pytest", "pytest -q", project_root)
        record("pytest", ok, dur)
        all_ok = all_ok and ok

        if shutil.which("ruff"):
            ok, dur = run_step("ruff", "ruff check .", project_root)
            record("ruff", ok, dur)
            all_ok = all_ok and ok

    return all_ok, results


def main() -> int:
    parser = argparse.ArgumentParser(description="AISE 客观验证")
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    start = time.time()

    all_ok, results = detect_and_run(project_root)

    total = time.time() - start
    print(f"\n[AISE-verify] === 汇总 (用时 {total:.1f}s) ===")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['name']} ({r['sec']}s)")

    aise_dir = project_root / ".aise"
    if aise_dir.exists():
        metrics_path = aise_dir / "metrics.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "phase": "verify",
            "pass": all_ok,
            "duration_sec": round(total, 1),
            "steps": results,
        }
        with metrics_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not all_ok:
        print("[AISE-verify] 硬门禁未通过，请回到执行阶段修复")
        return 1

    print("[AISE-verify] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
