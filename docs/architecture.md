# AISE 架构图（v3.6.0）

> Mermaid 图（GitHub 原生渲染），描述 AISE 5 层组件 + 三阶段闭环 + 数据流。

---

## 1. 整体架构（5 层）

```mermaid
graph TB
    subgraph U["用户层"]
        User["Claude Code 用户<br/>/aise &lt;任务描述&gt;"]
    end

    subgraph O["编排层（aise- 前缀 Skills + slash command）"]
        Cmd["commands/aise.md<br/>9 阶段编排"]
        SK1["aise-brainstorming"]
        SK2["aise-test-driven-development"]
        SK3["aise-ce-review"]
        SK4["aise-planning-with-files"]
        SK5["aise-verification-before-completion"]
        SK6["aise-ce-compound"]
    end

    subgraph G["三阶段闭环 Gate（v3.3 架构）"]
        G1["1️⃣ aise_run_init.py<br/>plan 校验 + run_id 分配<br/>+ snapshot 锁"]
        G2["2️⃣ aise_scope_check.py<br/>git diff vs task.scope.paths<br/>越界 → exit 1"]
        G3["3️⃣ aise_event.py<br/>6 pipe runner 调度<br/>+ evidence 签收"]
        G4["4️⃣ aise_verify.py<br/>--verify-evidence<br/>machine signoff"]
    end

    subgraph E["执行层（6 pipe runner）"]
        P1["go-test-json-to-junit"]
        P2["mvn-surefire"]
        P3["pytest-junitxml"]
        P4["jest-junit"]
        P5["cargo-test-junit"]
        P6["cargo-nextest-junit ⭐"]
    end

    subgraph L["lib/ 共用 helper（11 模块）"]
        L1["lock.py<br/>跨平台 mkdir 锁<br/>+ Windows ctypes pid"]
        L2["event_runner.py<br/>PIPE_DEFS + preflight<br/>+ defense_in_depth<br/>+ resolve_runtime_bin"]
        L3["target_cover.py<br/>cross-kind 桥接<br/>testcase → package"]
        L4["evidence.py<br/>sha256 + mtime<br/>+ 生成窗口签收"]
        L5["snapshot.py<br/>plan.snapshot 防篡改<br/>+ process-local 缓存"]
        L6["preflight.py / surefire_collector.py /<br/>region_detect.py / mirror_config.py /<br/>ansi.py / version_check.py"]
    end

    subgraph S["状态层 .aise/"]
        S1["plan.json + plan.md<br/>（人类 + 机器双源）"]
        S2["plan.snapshot.json<br/>+ .sha256<br/>（防篡改快照）"]
        S3["runs/&lt;run_id&gt;/<br/>├── run_context.json<br/>├── evidence.jsonl<br/>└── test_reports/*.xml"]
    end

    User --> Cmd
    Cmd --> SK1
    Cmd --> SK2
    Cmd --> SK3
    Cmd --> SK4
    Cmd --> SK5
    Cmd --> SK6

    Cmd --> G1
    G1 --> G2
    G2 --> G3
    G3 --> G4

    G3 -->|spawn| P1
    G3 -->|spawn| P2
    G3 -->|spawn| P3
    G3 -->|spawn| P4
    G3 -->|spawn| P5
    G3 -->|spawn| P6

    G1 -.read.-> S1
    G1 -.write.-> S2
    G1 -.write.-> S3
    G2 -.read.-> S2
    G2 -.read.-> S3
    G3 -.write.-> S3
    G4 -.read.-> S3

    G1 -.uses.-> L1
    G1 -.uses.-> L5
    G3 -.uses.-> L2
    G3 -.uses.-> L4
    G3 -.uses.-> L6
    G4 -.uses.-> L4
    G4 -.uses.-> L5

    classDef gate fill:#fff3cd,stroke:#856404
    classDef pipe fill:#d1ecf1,stroke:#0c5460
    classDef lib fill:#e8e8e8,stroke:#333
    classDef state fill:#d4edda,stroke:#155724
    class G1,G2,G3,G4 gate
    class P1,P2,P3,P4,P5,P6 pipe
    class L1,L2,L3,L4,L5,L6 lib
    class S1,S2,S3 state
```

---

## 2. 三阶段闭环流程（核心）

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant CC as Claude Code
    participant SK as Skills
    participant RI as aise_run_init
    participant SC as aise_scope_check
    participant EV as aise_event
    participant VF as aise_verify
    participant FS as .aise/

    U->>CC: /aise 给 X 加 Y 功能
    CC->>SK: brainstorming → requirements
    CC->>U: EnterPlanMode（用户审查）
    U-->>CC: ExitPlanMode（批准 plan.json）

    Note over CC,FS: 阶段 1: run_init
    CC->>RI: --project-root + --task-title-override
    RI->>FS: 读 plan.json
    RI->>RI: schema 校验<br/>(task_id 唯一 / scope 非空 /<br/> pipe 合法 / deps 无环 /<br/> shared_evidence scope 相交)
    RI->>FS: 写 plan.snapshot.json + .sha256
    RI->>FS: 写 runs/&lt;run_id&gt;/run_context.json
    RI-->>CC: run_id

    Note over CC,FS: TDD 任务执行（SubAgent + worktree）
    CC->>SK: aise-test-driven-development
    SK->>SK: Red → Green → Refactor

    Note over CC,FS: 阶段 2: scope_check
    CC->>SC: --task-id T-001
    SC->>FS: 读 runs/&lt;run_id&gt;/run_context.json
    SC->>SC: 校验 plan.snapshot.sha256<br/>（process-local cache）
    SC->>SC: git diff + ls-files<br/>vs task.scope.paths
    alt 越界
        SC-->>CC: exit 1 + 违规文件列表
        CC->>CC: worker 回退非范围内改动
    end
    SC-->>CC: exit 0

    Note over CC,FS: 阶段 3: event runner
    CC->>EV: --pipe pytest-junitxml --run-id
    EV->>EV: preflight_pipe（缺工具 exit 127）
    EV->>EV: defense_in_depth_check<br/>（target vs white-list）
    EV->>EV: spawn 真实测试命令
    EV->>FS: 写 test_reports/junit.xml
    EV->>FS: 写 evidence.jsonl<br/>(path + sha256 + mtime + window)
    EV-->>CC: actual_test_targets[]

    Note over CC,FS: 阶段 4: verify (machine signoff)
    CC->>VF: --verify-evidence
    VF->>FS: 读 evidence.jsonl
    VF->>VF: 重算每个 artifact 的 sha256
    VF->>VF: 检查 mtime 仍在 ±2s 窗口
    alt 篡改
        VF-->>CC: exit 1 + 违规项
    end
    VF-->>CC: exit 0（机器签收通过）

    CC->>SK: aise-ce-review（多 persona 审查）
    CC->>SK: aise-ce-compound（沉淀 patterns）
    CC-->>U: 任务完成（含 commit + diff）
```

---

## 3. 6 pipe runner 内部分发

```mermaid
flowchart TD
    Start["aise_event.py --pipe X"]

    Start --> Pre["preflight_pipe(X)"]
    Pre -->|缺工具| Exit127["exit 127<br/>+ 平台特定<br/>安装命令"]
    Pre -->|OK| Def["defense_in_depth_check<br/>target vs allowed_patterns"]
    Def -->|越界| Exit2["exit 2"]
    Def -->|OK| Disp["dispatch by pipe name"]

    Disp -->|go-test-json-to-junit| Go["spawn go test -v -json<br/>↓ pipe<br/>go-junit-report -out junit.xml"]
    Disp -->|mvn-surefire| Mvn["spawn mvn test<br/>+ surefire_collector<br/>(hard-link → copy fallback)"]
    Disp -->|pytest-junitxml| Pyt["spawn pytest<br/>--junit-xml=out.xml"]
    Disp -->|jest-junit| Je["spawn ./node_modules/.bin/jest<br/>+ JEST_JUNIT_OUTPUT_DIR env"]
    Disp -->|cargo-test-junit| Ct["spawn cargo test --no-fail-fast<br/>RUSTC_BOOTSTRAP=1 -Z unstable<br/>↓ pipe<br/>cargo2junit"]
    Disp -->|cargo-nextest-junit ⭐| Cn["spawn cargo nextest run<br/>(读 .config/nextest.toml<br/>原生 JUnit + stable Rust)"]

    Go --> Parse["_parse_junit_targets()<br/>提 testcase.name<br/>+ parent_package"]
    Mvn --> Parse
    Pyt --> Parse
    Je --> Parse
    Ct --> Parse
    Cn --> Parse

    Parse --> Coll["collect_artifact()<br/>sha256 + mtime + window"]
    Coll --> Ev["写 evidence.jsonl"]
    Ev --> Sum["输出 summary JSON<br/>含 actual_test_targets[]"]

    classDef fail fill:#f8d7da,stroke:#721c24
    classDef ok fill:#d4edda,stroke:#155724
    class Exit127,Exit2 fail
    class Ev,Sum ok
```

---

## 4. 数据流：plan.json → run_context → evidence

```mermaid
flowchart LR
    PlanMd[".aise/plan.md<br/>（人类描述）"]
    PlanJson[".aise/plan.json<br/>{schema_version,<br/> task_title,<br/> tasks: [<br/>  {task_id, scope.paths,<br/>   test_manifest.pipe, ...}<br/> ]}"]

    Snapshot[".aise/plan.snapshot.json<br/>+ .sha256<br/>（防篡改 / process-local cache）"]

    RunCtx[".aise/runs/&lt;run_id&gt;/<br/>run_context.json<br/>{schema_version, run_id,<br/> plan_snapshot.sha256,<br/> git.head, scope_policy,<br/> tasks: [...]}"]

    Evidence[".aise/runs/&lt;run_id&gt;/<br/>evidence.jsonl<br/>每行一个 artifact:<br/>{path, sha256, mtime_ms,<br/> window_start_ms,<br/> window_end_ms, runner, source}"]

    Reports[".aise/runs/&lt;run_id&gt;/<br/>test_reports/*.xml<br/>（6 pipe runner 产出）"]

    User[用户/AI 编辑] --> PlanMd
    User --> PlanJson
    PlanJson -->|aise_run_init<br/>校验 + 哈希| Snapshot
    PlanJson -->|aise_run_init<br/>赋 run_id| RunCtx
    Snapshot -.cache.-> RunCtx
    RunCtx -->|aise_scope_check<br/>读 + 比对 sha256| Gate1[gate 决策]
    RunCtx -->|aise_event<br/>找 task.test_manifest| Pipe[6 pipe runner]
    Pipe --> Reports
    Reports -->|collect_artifact<br/>sha256 + mtime| Evidence
    Evidence -->|aise_verify --verify-evidence<br/>重算 sha + 检 mtime ±2s| Gate2[machine signoff]
```

---

## 5. machine signoff 防篡改窗口

```mermaid
stateDiagram-v2
    [*] --> PlanLocked: ExitPlanMode
    PlanLocked: plan.snapshot.json 锁定<br/>+ sha256 计算

    PlanLocked --> RunningTests: aise_event spawn pipe
    RunningTests: window_start_ms = now()<br/>真实测试命令运行
    RunningTests --> EvidenceWritten: collect_artifact()
    EvidenceWritten: 每个产物:<br/>- sha256(content)<br/>- mtime_ms = fs.stat().mtime<br/>- window_end_ms = now()
    EvidenceWritten --> EvidenceLocked: write_evidence.jsonl

    EvidenceLocked --> VerifyOk: aise_verify --verify-evidence
    EvidenceLocked --> Tampered: 外部篡改 artifact
    Tampered: actual_sha != recorded_sha<br/>或<br/>actual_mtime ∉ [start-2s, end+2s]
    Tampered --> [*]: exit 1 + 列出违规

    VerifyOk: ✅ machine signoff 通过<br/>（不信任 Agent 自报，<br/>基于机器签收）
    VerifyOk --> [*]
```

---

## 6. 跨平台关键差异（v3.3 P0 实战验证）

```mermaid
graph TB
    subgraph "macOS APFS"
        M1[os.kill pid, 0]
        M2[路径 forward slash]
        M3[stdio utf-8 默认]
        M4[hard-link APFS]
    end

    subgraph "Linux ext4"
        L1[同 macOS]
        L2[同]
        L3[同]
        L4[同 / ext4]
    end

    subgraph "Windows NTFS"
        W1["ctypes 调 kernel32<br/>OpenProcess +<br/>GetExitCodeProcess +<br/>STILL_ACTIVE 259"]
        W2["路径 backslash<br/>→ _normalize_path<br/>归一为 /"]
        W3["cp1252 默认<br/>必装 PYTHONUTF8=1<br/>+ subprocess<br/>encoding='utf-8'"]
        W4["NTFS 同盘 OK<br/>跨盘 → copy 回退<br/>(6 种 OSError mock)"]
    end

    classDef mac fill:#d4edda
    classDef linux fill:#d4edda
    classDef win fill:#fff3cd,stroke:#856404
    class M1,M2,M3,M4 mac
    class L1,L2,L3,L4 linux
    class W1,W2,W3,W4 win
```

---

## 相关文档

- [`aise-guide.md`](aise-guide.md) — v3.6 实施指南（用户视角）
- [`plan-schema.md`](plan-schema.md) — plan.json schema v1.0
- [`tutorial.md`](tutorial.md) — 使用教程（step-by-step）
- [`tool-compatibility-matrix.md`](tool-compatibility-matrix.md) — 6 pipe 版本支持
- [`v3.4-6-completion-report.md`](v3.4-6-completion-report.md) — v3.6 完成度

---

_本架构图由 AISE 团队维护。v3.6.0 截图。_
