"""启动：uv run uvicorn opsagent.main:app --host 127.0.0.1 --port 8000"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from opsagent.agent.deps import Deps
from opsagent.agent.graph import build_graph
from opsagent.agent.llm import OpenAICompatLLM
from opsagent.api.app import create_app
from opsagent.config import Settings
from opsagent.container import Container
from opsagent.gateway.adapters.mock import MockScenario
from opsagent.gateway.gateway import Gateway
from opsagent.gateway.tools import build_registry
from opsagent.nacos.cache import FileCache
from opsagent.nacos.source import SdkNacosSource, SeedDirSource
from opsagent.nacos.store import ConfigStore
from opsagent.runner.runner import Runner
from opsagent.storage.db import make_engine, make_sessionmaker
from opsagent.storage.repo import DbRecorder, RunRepo, TopologyRepo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app):
    s = Settings()
    engine = make_engine(s.db_url)
    sm = make_sessionmaker(engine)
    topo = await TopologyRepo(sm).load()
    if not topo.nodes():
        raise RuntimeError("拓扑为空，请先执行 python -m opsagent.topology.load fixtures/topology.yaml")
    registry = build_registry(topo, MockScenario.from_yaml_file(s.scenarios_dir / f"{s.mock_scenario}.yaml"))

    if s.nacos_mode == "seed":
        source = SeedDirSource(Path("nacos_seed"))
    else:
        source = SdkNacosSource(s)
        await source.start()
    store = ConfigStore(source, FileCache(s.cache_dir), s.nacos_label, registry.ids())
    await store.load()

    recorder = DbRecorder(sm)
    gateway = Gateway(registry, topo, recorder, store.redactor, timeout_s=s.tool_timeout_s, retries=s.tool_retries)
    deps = Deps(llm=OpenAICompatLLM.from_settings(s), store=store, gateway=gateway, topo=topo)
    runs = RunRepo(sm)
    async with AsyncPostgresSaver.from_conn_string(s.checkpoint_db_url) as saver:
        runner = Runner(build_graph(deps, saver), runs, store, timedelta(minutes=s.clarify_timeout_min))
        app.state.c = Container(runner=runner, runs=runs, recorder=recorder)
        refresh = asyncio.create_task(store.run_refresh_loop(s.nacos_poll_s))
        try:
            yield
        finally:
            refresh.cancel()
            await runner.drain()
            if isinstance(source, SdkNacosSource):
                await source.close()
            await engine.dispose()


app = create_app(lifespan=lifespan)
