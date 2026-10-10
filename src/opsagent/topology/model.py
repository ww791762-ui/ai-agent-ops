import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["proxy", "lb", "api_gateway", "sidecar_proxy", "service", "endpoint", "game_server", "external"]

# 每种节点类型在细线阶段可用的排查工具
TOOLS_BY_TYPE: dict[str, list[str]] = {
    "proxy": ["logs.search"],
    "lb": [],
    "api_gateway": ["kong.upstream_health", "metrics.query"],
    "sidecar_proxy": [],
    "service": ["metrics.query", "logs.search", "changes.list"],
    "endpoint": ["metrics.query", "logs.search"],
    "game_server": ["metrics.query"],
    "external": [],
}


class Node(BaseModel):
    id: str
    type: NodeType
    name: str
    aliases: list[str] = Field(default_factory=list)
    env: str = "prod"
    parent: str | None = None
    description: str = ""


class Edge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    protocol: str = "http"
    timeout: str | None = None
    route_rule: str | None = None
    description: str = ""


class PathDef(BaseModel):
    id: str
    entry: str
    endpoint: str
    hops: list[str]


class Hop(BaseModel):
    node_id: str
    type: str
    name: str
    description: str = ""
    tools: list[str]
    next_protocol: str | None = None
    next_timeout: str | None = None


class TracedPath(BaseModel):
    path_id: str
    entry: str
    endpoint: str
    hops: list[Hop]


def _norm(text: str) -> str:
    return re.sub(r"[\s\-_/（）()]", "", text.lower()).removesuffix("服务")


class Topology:
    def __init__(self, nodes: list[Node], edges: list[Edge], paths: list[PathDef]) -> None:
        self._nodes = {n.id: n for n in nodes}
        self._edges = list(edges)
        self._edge_map = {(e.from_id, e.to_id): e for e in edges}
        self._paths = list(paths)
        self._validate()

    def _validate(self) -> None:
        for n in self._nodes.values():
            if n.parent and n.parent not in self._nodes:
                raise ValueError(f"节点 {n.id} 的 parent 不存在: {n.parent}")
        for e in self._edges:
            for nid in (e.from_id, e.to_id):
                if nid not in self._nodes:
                    raise ValueError(f"边引用了不存在的节点: {nid}")
        for p in self._paths:
            for nid in p.hops:
                if nid not in self._nodes:
                    raise ValueError(f"路径 {p.id} 引用了不存在的节点: {nid}")
            for a, b in zip(p.hops, p.hops[1:]):
                if (a, b) not in self._edge_map:
                    raise ValueError(f"路径 {p.id} 中 {a} -> {b} 没有对应的边")

    def get(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def edges(self) -> list[Edge]:
        return list(self._edges)

    def paths(self) -> list[PathDef]:
        return list(self._paths)

    def find(self, text: str) -> list[Node]:
        key = _norm(text)
        if not key:
            return []
        return [n for n in self._nodes.values()
                if key in {_norm(n.id), _norm(n.name), *(_norm(a) for a in n.aliases)}]

    def trace(self, node_id: str) -> list[TracedPath]:
        result = []
        for p in self._paths:
            if node_id not in p.hops and not any(self._nodes[h].parent == node_id for h in p.hops):
                continue
            hops = []
            for i, nid in enumerate(p.hops):
                n = self._nodes[nid]
                edge = self._edge_map.get((nid, p.hops[i + 1])) if i + 1 < len(p.hops) else None
                hops.append(Hop(node_id=n.id, type=n.type, name=n.name, description=n.description,
                                tools=TOOLS_BY_TYPE[n.type],
                                next_protocol=edge.protocol if edge else None,
                                next_timeout=edge.timeout if edge else None))
            result.append(TracedPath(path_id=p.id, entry=p.entry, endpoint=p.endpoint, hops=hops))
        return result


def load_topology_yaml(text: str) -> Topology:
    data = yaml.safe_load(text) or {}
    return Topology(
        nodes=[Node.model_validate(n) for n in data.get("nodes", [])],
        edges=[Edge.model_validate(e) for e in data.get("edges", [])],
        paths=[PathDef.model_validate(p) for p in data.get("paths", [])],
    )
