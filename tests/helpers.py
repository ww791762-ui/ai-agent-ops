import io
import zipfile

import yaml

from opsagent.nacos.source import PromptDoc

TOOL_IDS = {"topology.trace", "metrics.query", "logs.search", "changes.list", "kong.upstream_health"}


def make_skill_zip(meta: dict, instructions: str = "# 说明\n按步骤排查") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{meta['id']}/skill.yaml", yaml.safe_dump(meta, allow_unicode=True))
        zf.writestr(f"{meta['id']}/SKILL.md", instructions)
    return buf.getvalue()


class DictSource:
    """内存版 NacosSource；把 down 设为 True 可以模拟 Nacos 不可用。"""

    def __init__(self) -> None:
        self.prompts: dict[str, PromptDoc] = {}
        self.skills: dict[str, bytes] = {}
        self.configs: dict[tuple[str, str], str] = {}
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise ConnectionError("nacos down")

    async def get_prompt(self, key: str, label: str) -> PromptDoc:
        self._check()
        return self.prompts[key]

    async def get_skill_zip(self, name: str, label: str) -> bytes:
        self._check()
        return self.skills[name]

    async def get_config(self, data_id: str, group: str) -> str:
        self._check()
        return self.configs[(data_id, group)]


from pathlib import Path  # noqa: E402

from opsagent.agent.deps import Deps  # noqa: E402
from opsagent.agent.scripted_llm import ScriptedLLM  # noqa: E402
from opsagent.gateway.adapters.mock import MockScenario  # noqa: E402
from opsagent.gateway.gateway import Gateway  # noqa: E402
from opsagent.gateway.tools import build_registry  # noqa: E402
from opsagent.gateway.types import InMemoryRecorder  # noqa: E402
from opsagent.nacos.cache import FileCache  # noqa: E402
from opsagent.nacos.source import SeedDirSource  # noqa: E402
from opsagent.nacos.store import ConfigStore  # noqa: E402
from opsagent.topology.model import Topology, load_topology_yaml  # noqa: E402

NOW = "2026-10-10T10:00:00+08:00"


def load_topo() -> Topology:
    return load_topology_yaml(Path("fixtures/topology.yaml").read_text(encoding="utf-8"))


async def seed_store(tmp_path) -> ConfigStore:
    ids = build_registry(load_topo(), MockScenario(name="x", responses=[])).ids()
    store = ConfigStore(SeedDirSource(Path("nacos_seed")), FileCache(tmp_path / "cache"), "stable", ids)
    await store.load()
    return store


async def make_deps(tmp_path, script, scenario: str = "b_pay_slow", recorder=None):
    topo = load_topo()
    store = await seed_store(tmp_path)
    registry = build_registry(topo, MockScenario.from_yaml_file(Path(f"fixtures/scenarios/{scenario}.yaml")))
    rec = recorder if recorder is not None else InMemoryRecorder()
    llm = ScriptedLLM(script)
    gateway = Gateway(registry, topo, rec, store.redactor, backoff_s=0)
    return Deps(llm=llm, store=store, gateway=gateway, topo=topo), llm, rec


def skill_ref(store: ConfigStore, name: str) -> dict:
    s = store.skill(name)
    return {"id": s.meta.id, "version": s.meta.version, "md5": s.md5}
