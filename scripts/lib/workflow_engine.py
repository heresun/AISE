"""声明式工作流引擎（v4.0）

零外部依赖，纯 Python 标准库实现。
核心职责：解析 workflow.json（DAG），根据当前节点 + 退出码计算下一步节点。

用法：
    from lib.workflow_engine import Workflow
    wf = Workflow.from_file(".aise/workflow.json")
    next_nodes = wf.next_from("brainstorm", exit_code=0)
    # → ["plan_mode"]

节点类型：
    script         — Python 脚本 (subprocess)
    skill          — Claude Code Skill
    human_approval — 等待用户批准
    foreach        — 遍历 items，对每个执行 template 子图
    subgraph       — 引用另一个工作流
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


NODE_TYPES = ("script", "skill", "human_approval", "foreach", "subgraph")


class WorkflowError(Exception):
    pass


class Workflow:
    __slots__ = ("nodes", "edges", "start", "allow_cycles", "_adj", "_validated")

    def __init__(self, definition: dict):
        self.nodes: Dict[str, dict] = definition.get("nodes", {})
        self.edges: List[dict] = definition.get("edges", [])
        self.start: Optional[str] = definition.get("start")
        self.allow_cycles: bool = definition.get("allow_cycles", False)
        self._adj: Dict[str, List[Tuple[str, Optional[str]]]] = {}
        self._validated = False
        self._build_graph()

    @classmethod
    def from_file(cls, path: str | Path) -> Workflow:
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def _build_graph(self) -> None:
        self._adj = {}
        for edge in self.edges:
            frm = edge["from"]
            to = edge["to"]
            cond = None
            if "on_failure" in edge:
                if edge["on_failure"]:  # truthy → on_failure 语义
                    cond = "on_failure"
            elif "condition" in edge:
                cond = str(edge["condition"])
            self._adj.setdefault(frm, []).append((to, cond))

    # ---------------------------------------------------------------
    # 查询
    # ---------------------------------------------------------------

    def node(self, node_id: str) -> Optional[dict]:
        return self.nodes.get(node_id)

    def next_from(self, from_node: str, exit_code: int = 0) -> List[str]:
        """给定当前节点和退出码，返回下一步应执行的节点列表。

        条件边解释：
          - 无条件边：总是生效
          - "on_failure" → exit_code != 0 时生效
          - "exit_code == N" → exit_code == N 时生效
        """
        candidates = self._adj.get(from_node, [])
        result: List[str] = []
        for to, cond in candidates:
            if cond is None:
                result.append(to)
            elif cond == "on_failure" and exit_code != 0:
                result.append(to)
            elif cond.startswith("exit_code =="):
                try:
                    expected = int(cond.split("==")[1].strip())
                except (IndexError, ValueError):
                    continue
                if exit_code == expected:
                    result.append(to)
        return result

    def all_nodes(self) -> Set[str]:
        return set(self.nodes.keys())

    def start_node(self) -> Optional[str]:
        return self.start

    # ---------------------------------------------------------------
    # 校验
    # ---------------------------------------------------------------

    def validate(self) -> List[str]:
        errors: List[str] = []

        # 1) 基本：node type 合法
        for nid, nd in self.nodes.items():
            nt = nd.get("type", "")
            if nt not in NODE_TYPES:
                errors.append(f"节点 [{nid}] type='{nt}' 不在合法范围 {NODE_TYPES}")
            if nt == "foreach":
                if "items" not in nd:
                    errors.append(f"foreach 节点 [{nid}] 缺少 'items' 字段")
                if "template" not in nd:
                    errors.append(f"foreach 节点 [{nid}] 缺少 'template' 字段")

        # 2) 边引用有效节点
        node_ids = set(self.nodes.keys())
        for edge in self.edges:
            if "from" not in edge:
                errors.append("边缺少 'from' 字段")
                continue
            if "to" not in edge:
                errors.append(f"边 from='{edge.get('from')}' 缺少 'to' 字段")
                continue
            if edge["from"] not in node_ids:
                errors.append(f"边 from='{edge['from']}' 引用未定义的节点")
            if edge["to"] not in node_ids:
                errors.append(f"边 to='{edge['to']}' 引用未定义的节点")

        # 3) start 节点存在
        if self.start is not None and self.start not in node_ids:
            errors.append(f"start 节点 '{self.start}' 未定义")

        # 4) 从 start 可达性检测
        if self.start and self.start in node_ids:
            reachable = self._reachable_from(self.start)
            unreachable = node_ids - reachable
            if unreachable:
                errors.append(f"从 start 不可达的节点: {sorted(unreachable)}")

        # 5) 环路检测
        if not self.allow_cycles:
            cycles = self._detect_cycles()
            if cycles:
                for cycle in cycles:
                    errors.append(f"检测到环路: {' → '.join(cycle)} → {cycle[0]}")

        self._validated = True
        return errors

    def _reachable_from(self, root: str) -> Set[str]:
        visited: Set[str] = set()
        stack = [root]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            for to, _ in self._adj.get(n, []):
                if to not in visited:
                    stack.append(to)
        return visited

    def _detect_cycles(self) -> List[List[str]]:
        cycles: List[List[str]] = []
        visited: Set[str] = set()
        path: List[str] = []
        path_set: Set[str] = set()

        def dfs(n: str) -> None:
            if n in path_set:
                idx = path.index(n)
                cycles.append(list(path[idx:]))
                return
            if n in visited:
                return
            visited.add(n)
            path.append(n)
            path_set.add(n)
            for to, _ in self._adj.get(n, []):
                dfs(to)
            path.pop()
            path_set.discard(n)

        for nid in list(self.nodes.keys()):
            if nid not in visited:
                path.clear()
                path_set.clear()
                dfs(nid)
        return cycles

    # ---------------------------------------------------------------
    # 序列化
    # ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "start": self.start,
            "nodes": self.nodes,
            "edges": self.edges,
        }
