from pydantic import BaseModel

from opsagent.topology.model import Topology

from ..registry import Adapter
from ..types import AdapterResult


def trace_adapter(topo: Topology) -> Adapter:
    async def run(args: BaseModel) -> AdapterResult:
        paths = topo.trace(args.node_id)
        if not paths:
            return AdapterResult(status="empty")
        return AdapterResult(status="ok", data=[p.model_dump() for p in paths])

    return run
