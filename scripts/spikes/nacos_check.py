"""一次性脚本：验证 Nacos 3.2.4 的 Admin 发布接口和 Python SDK 读取接口。不进入正式代码。"""
import asyncio
import io
import json
import zipfile

import httpx
from v2.nacos import ClientConfigBuilder, ConfigParam, NacosConfigService
from v2.nacos.ai.model.ai_param import DownloadSkillParam, GetPromptParam
from v2.nacos.ai.nacos_ai_service import NacosAIService

from opsagent.config import Settings

S = Settings()
BASE = f"http://{S.nacos_addr}/nacos"
NS = S.nacos_namespace


def login(c: httpx.Client) -> str:
    r = c.post(f"{BASE}/v3/auth/user/login",
               data={"username": S.nacos_username, "password": S.nacos_password.get_secret_value()})
    print("login ->", r.status_code, "keys:", sorted(r.json().keys()) if r.is_success else r.text[:200])
    r.raise_for_status()
    return r.json()["accessToken"]


def admin(c: httpx.Client, method: str, path: str, token: str, **kw) -> httpx.Response:
    r = c.request(method, f"{BASE}{path}", params={"accessToken": token, **kw.pop("params", {})}, **kw)
    print(f"{method} {path} ->", r.status_code, r.text[:300])
    return r


def skill_zip(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f"---\nname: {name}\ndescription: spike\n---\n# spike\n")
        zf.writestr(f"{name}/skill.yaml", f"id: {name}\nversion: 1.0.0\n")
    return buf.getvalue()


# 第一次运行（计划原文的接口）结论：
# - POST /v3/admin/ai/prompt（旧接口）= createDraft + submit，版本停在 reviewing，SDK 读取报 “Prompt version not online”；
# - upload/batch 不读 skill.yaml 的 version，SKILL.md frontmatter 没有 version 时版本为 0.0.1，所以 force-publish 1.0.0 返回 404。
# 修正后的流程：prompt 走 draft -> force-publish -> labels；skill 走单个 upload(targetVersion) -> force-publish -> labels。
def publish() -> None:
    with httpx.Client(timeout=20) as c:
        t = login(c)
        admin(c, "POST", "/v3/admin/ai/prompt/draft", t, data={
            "namespaceId": NS, "promptKey": "spike.test", "targetVersion": "1.0.0",
            "template": "hello {{name}}", "commitMsg": "spike"})
        admin(c, "POST", "/v3/admin/ai/prompt/force-publish", t, data={
            "namespaceId": NS, "promptKey": "spike.test", "version": "1.0.0", "updateLatestLabel": "true"})
        admin(c, "PUT", "/v3/admin/ai/prompt/labels", t, data={
            "namespaceId": NS, "promptKey": "spike.test", "labels": json.dumps({"stable": "1.0.0"})})
        for name in ("spike-skill", "spike_skill"):
            admin(c, "POST", "/v3/admin/ai/skills/upload", t,
                  data={"namespaceId": NS, "overwrite": "true", "targetVersion": "1.0.0", "commitMsg": "spike"},
                  files={"file": (f"{name}.zip", skill_zip(name), "application/zip")})
            admin(c, "POST", "/v3/admin/ai/skills/force-publish", t, data={
                "namespaceId": NS, "skillName": name, "version": "1.0.0", "updateLatestLabel": "true"})
            admin(c, "PUT", "/v3/admin/ai/skills/labels", t, data={
                "namespaceId": NS, "skillName": name, "labels": json.dumps({"latest": "1.0.0", "stable": "1.0.0"})})
            admin(c, "GET", "/v3/admin/ai/skills", t, params={"namespaceId": NS, "skillName": name})
        admin(c, "GET", "/v3/admin/ai/prompt/governance", t, params={"namespaceId": NS, "promptKey": "spike.test"})
        admin(c, "POST", "/v3/admin/cs/config", t, data={
            "namespaceId": NS, "dataId": "spike.yaml", "groupName": "OPS_AGENT", "content": "a: 1", "type": "yaml"})


async def read_back() -> None:
    cfg = (ClientConfigBuilder().server_address(S.nacos_addr).namespace_id(NS)
           .username(S.nacos_username).password(S.nacos_password.get_secret_value()).build())
    ai = await NacosAIService.create_ai_service(cfg)
    try:
        p = await ai.get_prompt(GetPromptParam(prompt_key="spike.test", label="stable"))
        print("prompt type:", type(p), "fields:", getattr(p, "__dict__", p))
    except Exception as e:
        print("prompt FAILED:", repr(e))
    for name in ("spike-skill", "spike_skill"):
        try:
            z = await ai.download_skill_zip(DownloadSkillParam(skill_name=name, label="stable"))
            print(f"skill zip {name}: type={type(z)}")
            if z:
                zf = zipfile.ZipFile(io.BytesIO(z))
                print("  names:", zf.namelist())
                for n in zf.namelist():
                    print("  ", n, "=>", zf.read(n)[:300])
        except Exception as e:
            print(f"skill zip {name} FAILED:", repr(e))
    cs = await NacosConfigService.create_config_service(cfg)
    try:
        print("config:", repr(await cs.get_config(ConfigParam(data_id="spike.yaml", group="OPS_AGENT"))))
    except Exception as e:
        print("config FAILED:", repr(e))
    await ai.shutdown()
    await cs.shutdown()


if __name__ == "__main__":
    publish()
    asyncio.run(read_back())
