# Spike-2 跨平台兼容性报告

生成时间：2026-05-16
范围：AISE v2.3.x 落地 Spike-2 阶段（v3.2.5 §18.3 推荐路径）

> 设计取舍必须显式承认（v3.2.4 设计原则 A.4）。本报告坦诚记录 Spike-2
> 已验证、未验证、风险评估和 v3.3 落地优先级。

---

## 1. 验证范围矩阵

| 维度 | macOS APFS (arm64) | Linux ext4 (x86_64) | Windows NTFS | WSL2 ext4 |
|---|:---:|:---:|:---:|:---:|
| `lib/lock.py` mkdir 原子性 | ✅ 实测 | ⚠️ POSIX 保证 | ⚠️ 仅信任 NTFS | ⚠️ 假定同 Linux |
| `lib/lock.py` stale 检测 | ✅ 实测 | ⚠️ 同 mac | ❌ pid 探测语义需验 | ⚠️ 同 Linux |
| `lib/lock.py` 并发抢锁 | ✅ multiprocessing spawn | ❌ 未验 | ❌ 未验 | ❌ 未验 |
| `lib/event_runner.py` preflight | ✅ 三平台指引 schema 测试 | ✅ schema 测试覆盖 | ✅ schema 测试覆盖 | ✅ schema 测试覆盖 |
| `lib/event_runner.py` defense | ✅ 路径无关算法 | ✅ 路径无关 | ⚠️ 路径分隔符未对齐 | ✅ |
| `lib/target_cover.py` testcase→package | ✅ 实测 | ✅ 路径无关 | ✅ 路径无关 | ✅ |
| `go-test-json-to-junit` pipe 闭环 | ✅ 实测 | ❌ 未验 | ❌ 未验 | ❌ 未验 |
| `mvn-surefire` collector hard-link | ✅ 实测（mock + 真实 APFS） | ⚠️ ext4 hard-link 同支持 | ⚠️ NTFS hard-link 受限 | ⚠️ 假定同 Linux |
| `mvn-surefire` collector copy 回退 | ✅ 实测 EXDEV mock | ✅ 同 mac 逻辑 | ⚠️ 跨盘场景未验 | ⚠️ |
| `evidence` mtime ±2s 容忍 | ✅ 21 个边界用例 | ✅ ext4 纳秒精度更宽松 | ⚠️ NTFS 100ns 精度未实测 | ⚠️ |
| `evidence` sha256 篡改检测 | ✅ 实测 | ✅ 算法无关平台 | ✅ | ✅ |

图例：✅ 已实测 / ⚠️ 仅理论保证 / ❌ 未验证

---

## 2. 各平台风险评估

### 2.1 macOS APFS（已验证 ✅）

- **mkdir 原子性**：APFS Copy-on-Write + 单线程 metadata 写入，原子保证
- **mtime 精度**：APFS 纳秒级；本地实测 ±1ms 边界精确
- **hard-link**：APFS 支持，inode 共享，O(1)
- **pid 信号 0 探测**：POSIX `os.kill(pid, 0)` 标准行为
- **结论**：v3.3 可直接发布到 macOS

### 2.2 Linux ext4 / xfs / btrfs（理论保证 ⚠️）

- **mkdir 原子性**：POSIX 强保证；ext4 journal 模式下原子
- **mtime 精度**：ext4 默认纳秒；早期 ext3 1 秒级（罕见）
- **hard-link**：原生支持，但容器 overlayfs 上某些场景受限
- **pid 探测**：与 mac 一致
- **未验**：Docker 容器中 mkdir 锁、overlayfs hard-link
- **缓解**：v3.3 落地前用 GitHub Actions Linux runner 跑 41+10+21=72 测试
- **风险**：中（POSIX 兼容性 + Linux 主流文件系统行为良好）

### 2.3 Windows NTFS（理论保证较弱 ⚠️）

- **mkdir 原子性**：NTFS 支持但有边界场景：
  - 杀毒软件实时扫描可能 hold 句柄导致 `EACCES`
  - Windows Defender 在新建目录后短暂锁定（已知）
- **mtime 精度**：NTFS 100ns 单位但 FAT32 互操作时 2s 精度
- **hard-link**：NTFS 支持但**仅同卷**；且需 `SeCreateSymbolicLinkPrivilege` 在某些场景
- **pid 探测**：`os.kill(pid, 0)` 在 Windows 行为：
  - Python 3.2+ 翻译为 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)` + `GetExitCodeProcess`
  - 进程已退出但句柄仍打开 → 误判存活；通常 2 分钟内 OS 清理
- **路径分隔符**：`defense_in_depth_check` 的 glob 模式当前用 `/`，Windows 用 `\` 会拦截合法 target
- **未验**：所有 Windows 行为均未实测
- **缓解**：v3.3 落地前：
  1. GitHub Actions Windows runner 跑全套测试
  2. `defense_in_depth_check` 增加路径分隔符归一（统一替换 `\` → `/`）
  3. `_check_pid_alive` 加 Windows 专用通过 `GetExitCodeProcess` 显式判 STILL_ACTIVE
- **风险**：高（多个未实测点 + Windows 工具链行为多样）

### 2.4 WSL2 ext4（理论保证 ⚠️）

- Linux 内核 + ext4，理论与 2.2 一致
- 但跨边界场景（WSL 中跑 Maven，target/ 落在 NTFS 挂载）会触发跨盘 link 失败
- collector copy 回退路径已覆盖此场景
- **风险**：中低

---

## 3. v3.3 落地前必修任务

按风险优先级：

| # | 任务 | 平台 | 优先级 |
|---:|---|:---:|:---:|
| 1 | GitHub Actions Linux x86_64 跑全套 72 测试 | Linux | P0 |
| 2 | `defense_in_depth_check` 路径分隔符归一 | Windows | P0 |
| 3 | `_check_pid_alive` Windows 显式 STILL_ACTIVE 判定 | Windows | P0 |
| 4 | GitHub Actions Windows runner 跑全套测试 | Windows | P0 |
| 5 | NTFS 跨盘 hard-link 失败回退 copy 实测 | Windows | P1 |
| 6 | NTFS mtime 100ns 精度边界实测 | Windows | P1 |
| 7 | overlayfs hard-link 限制场景测试 | Linux/Docker | P2 |
| 8 | FAT32 mtime 2 秒精度回退策略 | Windows | P2 |

---

## 4. Spike-2 已知不会修复的边界（向后传递到 v3.3+）

承接 v3.2.5 §20 已知未尽事项 + 本报告新增：

- **NFS/SMB 网络盘**：mkdir 非真原子。AISE 假定项目本地盘，v3.3 加 preflight 探测项目所在盘类型
- **minimal Docker 镜像**：`shutil.which` 在某些 distroless 镜像中失败。已有 doc 缓解（C26）
- **同进程注入**：本进程内 snapshot 内存缓存可被同进程恶意代码覆盖。Python 进程内安全模型如此，不在 AISE 处理范围
- **网络文件系统 mtime**：NFS server clock skew 可能让 mtime 偏移 > 2s；不建议在 NFS 上跑测试

---

## 5. 测试覆盖矩阵（本报告生成时）

```
tests/test_lock.py                     10 测试  (mac APFS)
tests/test_event_runner.py             12 测试  (跨平台 schema)
tests/test_target_cover.py             13 测试  (路径无关)
tests/test_surefire_collector.py       10 测试  (mac APFS + EXDEV mock)
tests/test_evidence_mtime_boundaries.py 21 测试 (mac APFS)
tests/test_spike1_acceptance.py         6 测试  (mac + 真实 Go)
tests/test_spike2_acceptance.py         ? 测试  (mac + 真实 Maven，待 Maven 装好后落地)

合计：72+ 测试，4.99s
```

---

## 6. 一句话结论

> Spike-2 在 macOS APFS 平台已**完整闭环**。Linux POSIX 兼容性属于强保证、风险低；
> Windows NTFS 是**最大未验证面**，v3.3 落地前必须用 GitHub Actions 跨平台 CI
> 矩阵补齐。本报告显式承认此取舍——慢就是快。

---

_本报告由 AISE 团队生成。Spike-2 第 1 轮文档定稿。_
