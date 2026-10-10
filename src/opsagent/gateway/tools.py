from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from opsagent.topology.model import Topology

from .adapters.mock import MockScenario, mock_adapter
from .adapters.topology import trace_adapter
from .registry import ToolRegistry, ToolSpec

Metric = Literal["qps", "error_rate", "status_5xx", "latency_p99", "upstream_latency_p99", "conn_pool_wait",
                 "timeout_count", "online_players", "cpu_usage", "mem_usage"]

_NODE = Field(description="拓扑中的节点 ID，例如 svc-b、kong；必须来自上下文或 topology_trace 的结果")
_FROM = Field(description="开始时间，ISO 8601，带时区，例如 2026-10-09T20:00:00+08:00")
_TO = Field(description="结束时间，ISO 8601，带时区")


class NodeArgs(BaseModel):
    node_id: str = _NODE


class MetricsArgs(BaseModel):
    node_id: str = _NODE
    metric: Metric = Field(description="指标名，只能从枚举中选择")
    time_from: datetime = _FROM
    time_to: datetime = _TO


class LogsArgs(BaseModel):
    node_id: str = _NODE
    filter: Literal["error", "slow", "all"] = Field("error", description="预定义过滤条件")
    time_from: datetime = _FROM
    time_to: datetime = _TO
    limit: int = Field(50, ge=1, le=200, description="最多返回的日志行数")


class ChangesArgs(BaseModel):
    node_id: str = _NODE
    time_from: datetime = _FROM
    time_to: datetime = _TO


def build_registry(topo: Topology, scenario: MockScenario) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(
        "topology.trace",
        "按节点 ID 展开它所在的完整链路，返回每一跳的类型、说明、可用工具，以及到下一跳的协议和超时。排查链路问题时先调用它。",
        NodeArgs, trace_adapter(topo)))
    reg.register(ToolSpec("metrics.query", "查询节点在时间范围内的指标曲线。",
                          MetricsArgs, mock_adapter(scenario, "metrics.query")))
    reg.register(ToolSpec("logs.search", "按预定义过滤条件检索节点日志，返回摘要和样本行。",
                          LogsArgs, mock_adapter(scenario, "logs.search")))
    reg.register(ToolSpec("changes.list", "查询节点在时间范围内的发布和配置变更记录。",
                          ChangesArgs, mock_adapter(scenario, "changes.list")))
    reg.register(ToolSpec("kong.upstream_health", "查询 Kong 上 upstream 的健康检查状态。",
                          NodeArgs, mock_adapter(scenario, "kong.upstream_health")))
    return reg
