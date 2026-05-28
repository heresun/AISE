"""Pipe Runner 抽象基类

每个 pipe runner 模块应导出一个符合此接口的函数（鸭子类型，不强制继承）：
    def run(project_root, targets, out_dir, run_id, **kwargs) -> tuple[int, dict]

新增 pipe 只需在 lib/runners/ 下新建一个模块，无需修改核心文件。
"""

from __future__ import annotations
