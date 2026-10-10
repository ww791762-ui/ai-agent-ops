"""用法：uv run python -m opsagent.topology.load fixtures/topology.yaml"""
import asyncio
import sys
from pathlib import Path

from opsagent.config import Settings
from opsagent.storage.db import make_engine, make_sessionmaker
from opsagent.storage.repo import TopologyRepo
from opsagent.topology.model import load_topology_yaml


async def main(path: str) -> None:
    topo = load_topology_yaml(Path(path).read_text(encoding="utf-8"))
    engine = make_engine(Settings().db_url)
    await TopologyRepo(make_sessionmaker(engine)).replace_all(topo, updated_by="seed")
    await engine.dispose()
    print(f"已导入 {len(topo.nodes())} 个节点、{len(topo.edges())} 条边、{len(topo.paths())} 条链路")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
