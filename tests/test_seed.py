import io
import zipfile
from pathlib import Path

import httpx

from opsagent.config import Settings
from opsagent.gateway.adapters.mock import MockScenario
from opsagent.gateway.tools import build_registry
from opsagent.nacos.cache import FileCache
from opsagent.nacos.source import SeedDirSource
from opsagent.nacos.store import ConfigStore
from opsagent.topology.model import load_topology_yaml

TOPO = load_topology_yaml(Path("fixtures/topology.yaml").read_text(encoding="utf-8"))
TOOL_IDS = build_registry(TOPO, MockScenario(name="x", responses=[])).ids()


async def test_seed_loads_into_store(tmp_path):
    store = ConfigStore(SeedDirSource(Path("nacos_seed")), FileCache(tmp_path), "stable", TOOL_IDS)
    await store.load()
    assert "{{now}}" in store.prompt("ops.system").template
    assert "{{history}}" in store.prompt("ops.intent").template
    assert "{{required_evidence}}" in store.prompt("ops.reflect.inrun").template
    assert store.prompt("ops.report").template
    assert {s.meta.id for s in store.skills()} == {"http_5xx", "topology_qa", "generic_troubleshoot"}
    assert store.skill("topology_qa").meta.allowed_tools == ["topology.trace"]
    assert "[REDACTED:bearer]" in store.redactor().redact_text("Bearer abc.def")


def test_publish_calls_expected_endpoints():
    from nacos_seed.publish import Publisher, batch_zip

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/user/login"):
            return httpx.Response(200, json={"accessToken": "tok"})
        assert request.url.params["accessToken"] == "tok"
        return httpx.Response(200, json={"code": 0, "message": "success", "data": True})

    client = httpx.Client(base_url="http://nacos/nacos", transport=httpx.MockTransport(handler))
    p = Publisher(client, Settings(_env_file=None))
    p.login()
    p.publish_all("stable")
    paths = [path for _, path in seen]
    assert paths.count("/nacos/v3/admin/ai/prompt") == 4
    assert paths.count("/nacos/v3/admin/ai/prompt/label") == 4
    assert paths.count("/nacos/v3/admin/ai/skills/upload/batch") == 1
    assert paths.count("/nacos/v3/admin/ai/skills/force-publish") == 3
    assert paths.count("/nacos/v3/admin/ai/skills/labels") == 3
    assert paths.count("/nacos/v3/admin/cs/config") == 1

    names = zipfile.ZipFile(io.BytesIO(batch_zip(["http_5xx", "topology_qa"]))).namelist()
    assert "http_5xx/skill.yaml" in names and "topology_qa/SKILL.md" in names
