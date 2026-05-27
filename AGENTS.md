# AISE — AI Agent Onboarding

> **下一个 AI 会话只读这一个文件就能 onboard**。
> 包含架构 + 关键决策 + 踩坑经验 + 常用命令。其他细节按需查 `docs/`。

最后更新：2026-05-27（v3.6.0，247 测试，全量已 push）

---

## 1. 一句话项目定位

AISE = Claude Code 插件，**端到端任务流程编排** + **machine signoff**
（机器签收，不信 Agent 自报）+ **6 种语言 pipe runner** + **三阶段闭环 gate**。
v3.6.0 已 release，247 测试全绿。

---

## 2. 架构速览（必读）

### 三阶段闭环
```
ExitPlanMode
  → aise_run_init.py    (plan 校验 + run_id + snapshot 锁)
  → worker TDD          (Claude Code 自身)
  → aise_scope_check.py (git diff vs task.scope.paths)
  → aise_event.py       (6 pipe 之一，evidence.jsonl 签收)
  → aise_verify.py      (--verify-evidence 复核 sha256 + mtime)
```

### 4 层组件
1. **编排层**：`/aise` slash command + 6 个 `aise-` 前缀 skill
2. **入口层**：`aise_run_init.py`（plan 校验 + run_id）
3. **Gate 层**：`aise_scope_check.py` + `aise_verify.py`
4. **执行层**：`aise_event.py` + 6 pipe runner

### 6 种 pipe（全部端到端验证过）
| pipe | 工具链 | preflight bin | runtime bin |
|---|---|---|---|
| go-test-json-to-junit | Go + go-junit-report v2 | go-junit-report | go-junit-report |
| mvn-surefire | mvn 3.6+ + Surefire 3.2+ | mvn | mvn |
| pytest-junitxml | Python 3.10+ + pytest 6+ | pytest（or python -m pytest）| 同 |
| jest-junit | node 18+ + jest 29+ + jest-junit 16 | **node** | `./node_modules/.bin/jest` |
| cargo-test-junit | stable Rust + cargo2junit | **cargo2junit** | **cargo**（RUSTC_BOOTSTRAP=1）|
| cargo-nextest-junit | stable Rust + cargo-nextest | **cargo-nextest** | **cargo**（无需 BOOTSTRAP）|

⚠️ **jest 和 cargo 的 preflight bin ≠ runtime bin**——`PIPE_DEFS.runtime_bin`
字段（v3.3 P1-1 引入）显式分离，用 `lib.event_runner.resolve_runtime_bin()`
统一解析。

---

## 3. 关键文件位置

### 必看（修改任何东西前）
- `commands/aise.md` — `/aise` 主流程定义，9 步骤
- `docs/plan-schema.md` — `.aise/plan.json` schema v1.0
- `docs/v3.3-completion-report.md` — v3.3 完成度（v3.2.5 §18 任务对照）

### 核心 scripts/
```
aise_run_init.py        三阶段第 1 步：plan 校验 + run_id
aise_event.py           三阶段第 3 步：6 pipe runner 调度
aise_scope_check.py     三阶段第 2 步：git diff vs scope
aise_verify.py          v1.1 evidence 复核（machine signoff）
aise_doctor.py          v3.4 一键自检环境（支持 --export / --strict / --check-versions）
aise_snapshot.py        v1.1 旧入口（仅 snapshot create/check）
aise_init.py            最早入口（初始化 .aise/ 目录）
aise_track.py / aise_fuse.py / aise_inject_context.py / aise_sediment.py / aise_dashboard.py
                        v1.0 时代 7 个脚本（保留，部分未升级）
```

### lib/ 共用 helper（凡是新功能优先放这里）
```
lib/event_runner.py     PIPE_DEFS + preflight + defense + resolve_runtime_bin
lib/lock.py             跨平台 mkdir 锁 + Windows ctypes pid（STILL_ACTIVE 259）
lib/evidence.py         sha256 + mtime + 生成窗口的签收链
lib/snapshot.py         plan.snapshot.json 防篡改 + in-memory 缓存
lib/target_cover.py     cross-kind targetCovers（testcase → package）
lib/preflight.py        通用工具预检 + 平台安装指引
lib/surefire_collector.py  Maven hard-link 优先 + EXDEV 回退 copy
lib/region_detect.py    v3.4 region 探测（env + timezone）
lib/mirror_config.py    v3.4 镜像源建议（brew/maven/pip/npm/cargo）
lib/ansi.py             v3.4 ANSI 颜色过滤
lib/version_check.py     v3.5 工具版本对比引擎（MINIMUMS + meets_minimum）
```

### 必读文档（按时间顺序）
1. `docs/aise-guide.md` — v3.3 实施指南（用户视角）
2. `docs/plan-schema.md` — plan.json schema
3. `docs/spike-2-compatibility.md` — 跨平台兼容性 + Windows 限制
4. `docs/spike-3-summary.md` — 5 pipe 全集落地
5. `docs/v3.3-completion-report.md` — v3.3 完成度 + v3.4 路线图
6. `docs/tool-compatibility-matrix.md` — 5 pipe 工具版本支持范围
7. `docs/rustc-bootstrap-risk.md` — RUSTC_BOOTSTRAP=1 风险评估
8. `CHANGELOG.md` — keep-a-changelog 风格

---

## 4. 已踩过的坑（不要再踩）

1. **go-junit-report v2 默认 suite.name 空** → 必须 fallback 解析 system-out
   内嵌 JSON events。`aise_event._parse_junit_targets` 已实现
2. **`-set-exit-code` 让 junit_proc 继承测试失败** → junit_ok 判定改用 "XML
   落盘 + 可解析"
3. **pip --user pytest 不在 PATH** → preflight_pipe 支持 alt_bins 走
   `python -m pytest`
4. **jest 在 fixture ./node_modules/.bin/jest** → PIPE_DEFS.runtime_bin
   分离，preflight 用 node
5. **cargo stdout 混编译信息** → 过滤 `{...}` 开头/结尾的纯 JSON 行
6. **stable Rust 不允许 -Z unstable-options** → `RUSTC_BOOTSTRAP=1` env
   绕开（见 docs/rustc-bootstrap-risk.md，v3.5 计划用 cargo-nextest 替代）
7. **cargo2junit 对空 stdin 返回空 `<testsuites/>`** → pipeline_ok 判定加
   `len(collected) > 0`
8. **企业内网 nexus 让 mvn 拉不到依赖** → fixture 用 `.mvn/maven.config`
   + `.mvn/settings.xml` 指阿里云
9. **国内 brew install 卡 USTC 镜像 20min+** → 改 archive.apache.org 或
   aliyun 直接下载二进制
10. **git status --porcelain 折叠 untracked 目录** → 用 `git diff --name-only`
    + `git ls-files --others` 组合
11. **Windows cp1252 解码中文 stderr 失败** → `PYTHONUTF8=1` env + subprocess
    显式 `encoding="utf-8"` 双层防御
12. **shared_evidence scope 简单 head segment 误判** → 用静态前缀 + 严格
    prefix 包含判定
13. **zsh `status` 是只读变量** → 不能用 `status=$(...)`，用别的名字
14. **git remote 是 SSH，HTTPS 没存 credential** → push 失败时改 `! git push`
     让用户在终端手动跑
15. **GitHub SSH 22 端口国内偶发被阻断** → 22/443/HTTPS 都可能 fail，等
    自愈或换 VPN

---

## 5. 跨平台关键差异

| 项 | macOS | Linux | Windows |
|---|---|---|---|
| pid 探测 | `os.kill(pid, 0)` | 同 mac | **ctypes 调 kernel32.OpenProcess + GetExitCodeProcess + STILL_ACTIVE (259)** |
| 路径分隔符 | `/` | `/` | `\` → glob 前 `_normalize_path` 归一 |
| stdio 编码 | utf-8 默认 | utf-8 默认 | **cp1252 默认 → 必须 `PYTHONUTF8=1`** |
| hard-link | APFS 同盘 OK | ext4 OK | NTFS 同盘 OK，跨盘失败 → copy 回退（mock 已覆盖，实测未做）|
| mtime 精度 | ns | ns | 100ns |
| timezone | Asia/Shanghai 等 | 同 | 简称 CST 不可靠（不用 time.tzname）|

---

## 6. 常用命令

### 跑测试
```bash
cd ~/.claude/plugins/marketplaces/aise
# 全套（不含 mvn，~15s）
python3 -m pytest tests/ -q --ignore=tests/test_spike2_acceptance.py --ignore=tests/fixtures
# 含 mvn 端到端（~8min，需 PATH 含 mvn）
PATH="$HOME/.local/apache-maven-3.9.9/bin:$PATH" python3 -m pytest tests/test_spike2_acceptance.py -v
```

### 跑 aise_doctor
```bash
PYTHONUTF8=1 python3 scripts/aise_doctor.py            # markdown
python3 scripts/aise_doctor.py --json                   # 机器可读
AISE_REGION=cn python3 scripts/aise_doctor.py           # 含镜像建议
python3 scripts/aise_doctor.py --strict                 # 任何 fail 都 fatal
```

### CI 状态查（无需 gh CLI）
```bash
curl -s "https://api.github.com/repos/heresun/AISE/actions/runs?per_page=1" | \
  python3 -c "import json,sys;r=json.loads(sys.stdin.read())['workflow_runs'][0]; \
print(f'run #{r[\"run_number\"]} {r[\"status\"]} ({r[\"head_sha\"][:10]})')"
```

### push 失败时
```bash
# 1. 不要无限重试 22 端口（GitHub 国内偶发阻断）
# 2. 等 30-60min 自愈
# 3. 或让用户在终端跑 ! git push origin main
```

---

## 7. 设计原则（KISS 至上）

1. **零外部依赖**：仅 Python 标准库；dev 仅 pytest
2. **永不抛异常给调用方**：`aise_doctor` / `aise_track` 等用户工具
   `except: pass` 兜底
3. **machine signoff > 自报**：通过判定基于机器签收（sha256 + mtime），
   不信任 Agent 输出文本
4. **可观测**：所有动作产生 JSONL 日志（`.aise/runs/<run_id>/`）
5. **可回滚**：所有破坏性操作有备份（snapshot / settings.bak）
6. **跨平台一等公民**：3 平台 × 2 Python = 6 个 Python unit CI jobs
7. **设计取舍显式承认**（v3.2.5 §A.4）：每个 deferred 项都在 changelog /
   docs 里写清楚原因

---

## 8. 测试体系（v3.6 完成时）

```
tests/test_lock.py                      10  lock 原子性 + stale
tests/test_lock_windows_pid.py           7  Windows ctypes
tests/test_event_runner.py              12  preflight + defense
tests/test_runtime_bin_resolver.py       9  runtime_bin 4 种解析
tests/test_target_cover.py              13  cross-kind 桥接
tests/test_surefire_collector.py        10  hard-link + EXDEV
tests/test_evidence_mtime_boundaries.py 21  ±2s 边界
tests/test_defense_path_separator.py     7  Windows 路径
tests/test_aise_run_init.py             18  plan 校验
tests/test_aise_scope_check.py          10  git diff vs scope
tests/test_aise_doctor.py               11  doctor 输出
tests/test_doctor_export.py              6  --export 导出
tests/test_doctor_check_versions.py     11  版本比较
tests/test_region_mirror.py             17  region detect + mirrors
tests/test_ansi.py                      19  ANSI 过滤
tests/test_snapshot.py                  11  create/check/cache
tests/test_preflight.py                 11  preflight + TOOL_DEPS
tests/test_cargo_nextest.py              8  cargo-nextest PIPE_DEFS + acceptance
tests/test_spike1_acceptance.py          6  Go pipe E2E
tests/test_spike2_acceptance.py          6  mvn pipe E2E（慢，~8min）
tests/test_spike3_pytest_acceptance.py   5  pytest pipe E2E
tests/test_spike3_jest_acceptance.py     4  jest pipe E2E
tests/test_spike3_cargo_acceptance.py    3  cargo pipe E2E

合计：247 测试（含 mvn）/ 241 全绿 20s 内（不含 mvn）
```

### CI 矩阵（GitHub Actions）
- 3 平台 × 2 Python = 6 Python unit jobs（必跑）
- 6 个 pipe runner 各自 job（mac + linux，部分含 windows）
- 总计 18 jobs / 1 个 workflow

---

## 9. 版本演进时间线

```
v1.0.0  e195c08  baseline 9 阶段编排
v1.1    59458e9  plan snapshot + machine signoff
Spike-1 b652361  跨平台锁 + Go pipe + targetCovers
Spike-2 fe0e729  mvn-surefire + mtime 边界
Spike-3 f6bc813  pytest + jest + cargo（5 pipe 全集）
v3.3 P0 74209ee  CI 矩阵 + Windows 路径分隔符 + Windows pid
v3.3 P1 61cfb95  PIPE_DEFS runtime_bin 分离
v3.3 架构 6c3b9d9  run_init + scope_check 三阶段闭环
v3.3 fix  f08059c  Windows UTF-8
v3.3 docs 22f0d2c  完成度报告 + 用户指南
v3.3.0  537bef4  CHANGELOG + git tag

v3.4 doctor      249c355  aise_doctor.py
v3.4 compat      26d4f7d  兼容性矩阵
v3.4 mirror     4d6756d  region + mirror
v3.4 ansi       8ddd0c4  ANSI 过滤
v3.4 rustc-risk 696a7f7  RUSTC_BOOTSTRAP 风险评估

v3.5 路线图（全部完成）:
- cargo-nextest-junit 第 6 个 pipe（消除 RUSTC_BOOTSTRAP=1）✅
- aise_doctor --check-versions（对比版本矩阵）✅
- 240 测试目标 ✅
- aise_gate_context.py（deferred，run_context.json 已含 per-task 信息）

v3.6.0  67ab99f  240 测试目标达成 + CI cargo-nextest + --export 导出
v3.6.0  355cb73  CHANGELOG v3.6.0 release notes
```

---

## 10. 接手要点

如果你是接手的 AI 会话：

1. **先读 docs/v3.3-completion-report.md** 知道 v3.2.5 落地了 61%
2. **先跑 `python3 scripts/aise_doctor.py`** 确认你的环境就绪
3. **先跑 `python3 -m pytest tests/ -q --ignore=tests/test_spike2_acceptance.py --ignore=tests/fixtures`**
   确认本地 241 测试全绿
4. **改任何代码前先看相关 lib/*.py 模块**——它们是核心，scripts/ 大多
   只是 CLI 入口
5. **新加 pipe** 时：参考 cargo-nextest 实现（v3.5 路线图）—— PIPE_DEFS
   + runner 函数 + parse_targets + fixture + acceptance test 五件套
6. **不要擅自改 git config / remote URL**（HTTPS 没
   credential 而 SSH 阻断时不要换 URL 救场）
7. **不要在没明确许可时 commit / push**

---

---
