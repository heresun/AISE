"""Pipe Runner 统一契约（v4.0 插件化）

每个 runner 模块导出三样东西，让 aise_event.py 不再 per-pipe if/elif：

  SPEC: dict — 描述该 pipe 的默认行为
      name: str                       pipe 名（== event_runner.PIPE_DEFS 的 key）
      default_allowed_patterns: list  defense-in-depth 默认白名单
      default_targets: list           未显式 --target 时的默认（defense 检查用）
      accepts_targets: bool           invoke 是否把 targets 传给 run（mvn/cargo 系为 False）

  run(...) — 实际执行函数（各 runner 私有签名，invoke 内部调用，外部不直接依赖）

  invoke(ctx: RunnerContext) -> tuple[int, dict] — 统一入口
      封装本 runner 自己的 run() 调用细节（主 bin / runtime_bin / extra 参数各自解析），
      使核心代码只需 invoke(ctx)，无需知道每个 run() 的私有签名。

新增 pipe = 新建 lib/runners/<x>_runner.py（含 run + SPEC + invoke）
+ 在 PIPE_DEFS 注册 bin/安装指引；aise_event.py 零改动（开闭原则）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class RunnerContext:
    """invoke() 的统一入参。aise_event 构建一次，分派给任意 runner。"""

    project_root: Path
    targets: List[str]                  # 原始 --target（可能为空；各 invoke 自行决定是否填默认）
    out_dir: Path
    run_id: str
    preflight_info: Dict[str, Any]      # er.preflight_pipe 返回的 info（含 "found"）
    extra: Dict[str, Any] = field(default_factory=dict)  # CLI 透传的 per-pipe 专属参数


class RuntimeBinMissing(Exception):
    """invoke 解析 runtime_bin 失败（如 cargo 不在 PATH）。核心捕获后 → exit 127。"""

    def __init__(self, info: Dict[str, Any]):
        super().__init__(str(info))
        self.info = info
