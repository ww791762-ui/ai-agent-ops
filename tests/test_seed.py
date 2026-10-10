import io
import json
import re
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


class FakeNacos:
    """按 spike 结论模拟 Nacos 3.2.4 Admin API：资源发布后 GET 详情才返回 200，label 表在 force-publish 时写入 latest。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.uploads: dict[str, bytes] = {}
        self.resources: dict[str, dict] = {}  # name -> {"versions": {v: status}, "labels": {...}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/user/login"):
            return httpx.Response(200, json={"accessToken": "tok"})
        assert request.url.params["accessToken"] == "tok"
        if request.method == "GET":
            form = dict(request.url.params)
        elif request.headers.get("content-type", "").startswith("multipart/form-data"):
            body = request.content
            zip_bytes = body[body.index(b"PK\x03\x04"):body.rindex(b"PK\x05\x06") + 22]
            skill_name = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()[0].split("/")[0]
            version = re.search(rb'name="targetVersion"\r\n\r\n([^\r]+)', body).group(1).decode()
            form = {"skillName": skill_name, "targetVersion": version}
            self.uploads[skill_name] = zip_bytes
        else:
            form = dict(httpx.QueryParams(request.content.decode()))
        self.calls.append((request.method, path, form))
        name = form.get("promptKey") or form.get("skillName")
        res = self.resources.get(name)
        if request.method == "GET":
            if res is None:
                return httpx.Response(404, json={"code": 20004, "message": "resource not found"})
            versions = [{"version": v, "status": st} for v, st in res["versions"].items()]
            return httpx.Response(200, json={"code": 0, "data": {"labels": res["labels"], "versions": versions,
                                                                 "versionDetails": versions}})
        if path.endswith(("/prompt/draft", "/skills/upload")):
            self.resources.setdefault(name, {"versions": {}, "labels": {}})["versions"][form["targetVersion"]] = "draft"
        if path.endswith("/force-publish"):
            res["versions"][form["version"]] = "online"
            res["labels"]["latest"] = form["version"]
        if path.endswith("/labels"):
            res["labels"] = json.loads(form["labels"])
        return httpx.Response(200, json={"code": 0, "message": "success", "data": "ok"})


def _publisher(fake: FakeNacos):
    from nacos_seed.publish import Publisher

    client = httpx.Client(base_url="http://nacos/nacos", transport=httpx.MockTransport(fake.handler))
    p = Publisher(client, Settings(_env_file=None))
    p.login()
    return p


def test_publish_calls_expected_endpoints():
    fake = FakeNacos()
    p = _publisher(fake)
    p.publish_all("stable")
    writes = [(m, path) for m, path, _ in fake.calls if m != "GET"]
    paths = [path for _, path in writes]
    assert paths.count("/nacos/v3/admin/ai/prompt/draft") == 4
    assert paths.count("/nacos/v3/admin/ai/prompt/force-publish") == 4
    assert paths.count("/nacos/v3/admin/ai/prompt/labels") == 4
    assert paths.count("/nacos/v3/admin/ai/skills/upload") == 3
    assert paths.count("/nacos/v3/admin/ai/skills/force-publish") == 3
    assert paths.count("/nacos/v3/admin/ai/skills/labels") == 3
    assert paths.count("/nacos/v3/admin/cs/config") == 1

    # Skill 名称换成连字符；label 表保留 force-publish 写入的 latest
    assert set(fake.resources) >= {"http-5xx", "topology-qa", "generic-troubleshoot"}
    assert fake.resources["http-5xx"]["labels"] == {"latest": "1.0.0", "stable": "1.0.0"}
    assert fake.resources["ops.system"]["labels"] == {"latest": "1.0.0", "stable": "1.0.0"}
    publish_forms = [f for m, path, f in fake.calls if path.endswith("/skills/force-publish")]
    assert {f["skillName"] for f in publish_forms} == {"http-5xx", "topology-qa", "generic-troubleshoot"}
    assert "http-5xx/SKILL.md" in zipfile.ZipFile(io.BytesIO(fake.uploads["http-5xx"])).namelist()

    # 再发布一次：版本已 online，只更新 label，不重复上传
    fake.calls.clear()
    p.publish_all("canary")
    paths = [path for m, path, _ in fake.calls if m != "GET"]
    assert not any(path.endswith(("/draft", "/upload", "/force-publish")) for path in paths)
    assert fake.resources["http-5xx"]["labels"] == {"latest": "1.0.0", "stable": "1.0.0", "canary": "1.0.0"}


def test_skill_upload_zip_uses_nacos_name():
    from nacos_seed.publish import skill_upload_zip

    zf = zipfile.ZipFile(io.BytesIO(skill_upload_zip("http_5xx")))
    assert set(zf.namelist()) == {"http-5xx/SKILL.md", "http-5xx/skill.yaml"}
    md = zf.read("http-5xx/SKILL.md").decode("utf-8")
    assert md.startswith("---\nname: http-5xx\n")
    assert "id: http_5xx" in zf.read("http-5xx/skill.yaml").decode("utf-8")
