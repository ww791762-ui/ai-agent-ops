"""把 nacos_seed/ 中的 Prompt、Skill、脱敏规则发布到 Nacos，并打上 label。

用法：uv run python -m nacos_seed.publish [--label stable]
接口路径和参数以 docs/superpowers/plans/2026-10-10-spike-results.md 的结论为准。
"""
import argparse
import io
import json
import zipfile
from pathlib import Path

import httpx
import yaml

from opsagent.config import Settings
from opsagent.nacos.skill import build_skill_zip

ROOT = Path(__file__).parent
LOGIN = "/v3/auth/user/login"
PROMPT_PUBLISH = ("POST", "/v3/admin/ai/prompt")
PROMPT_LABEL = ("PUT", "/v3/admin/ai/prompt/label")
SKILL_UPLOAD = ("POST", "/v3/admin/ai/skills/upload/batch")
SKILL_PUBLISH = ("POST", "/v3/admin/ai/skills/force-publish")
SKILL_LABEL = ("PUT", "/v3/admin/ai/skills/labels")
CONFIG_PUBLISH = ("POST", "/v3/admin/cs/config")


def batch_zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            with zipfile.ZipFile(io.BytesIO(build_skill_zip(ROOT / "skills" / name))) as one:
                for item in one.namelist():
                    out.writestr(item, one.read(item))
    return buf.getvalue()


class Publisher:
    def __init__(self, client: httpx.Client, settings: Settings) -> None:
        self._c = client
        self._s = settings
        self._token = ""

    def login(self) -> None:
        r = self._c.post(LOGIN, data={"username": self._s.nacos_username,
                                      "password": self._s.nacos_password.get_secret_value()})
        r.raise_for_status()
        self._token = r.json()["accessToken"]

    def _call(self, endpoint: tuple[str, str], **kw) -> dict:
        method, path = endpoint
        r = self._c.request(method, path, params={"accessToken": self._token}, **kw)
        r.raise_for_status()
        body = r.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"{method} {path} 失败: {body}")
        return body

    def publish_all(self, label: str) -> None:
        manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
        ns = self._s.nacos_namespace
        for key, p in manifest["prompts"].items():
            version = str(p["version"])
            self._call(PROMPT_PUBLISH, data={"namespaceId": ns, "promptKey": key, "version": version,
                                             "template": (ROOT / p["file"]).read_text(encoding="utf-8"),
                                             "commitMsg": "seed"})
            self._call(PROMPT_LABEL, data={"namespaceId": ns, "promptKey": key, "label": label, "version": version})
            print(f"Prompt {key} {version} -> {label}")
        skills = manifest["skills"]
        self._call(SKILL_UPLOAD, data={"namespaceId": ns, "overwrite": "true"},
                   files={"file": ("skills.zip", batch_zip(skills), "application/zip")})
        for name in skills:
            version = str(yaml.safe_load((ROOT / "skills" / name / "skill.yaml").read_text(encoding="utf-8"))["version"])
            self._call(SKILL_PUBLISH, data={"namespaceId": ns, "skillName": name, "version": version,
                                            "updateLatestLabel": "true"})
            self._call(SKILL_LABEL, data={"namespaceId": ns, "skillName": name,
                                          "labels": json.dumps({label: version})})
            print(f"Skill {name} {version} -> {label}")
        for c in manifest["config"]:
            self._call(CONFIG_PUBLISH, data={"namespaceId": ns, "dataId": c["data_id"], "groupName": c["group"],
                                             "content": (ROOT / c["file"]).read_text(encoding="utf-8"),
                                             "type": "yaml"})
            print(f"Config {c['group']}/{c['data_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="stable")
    args = parser.parse_args()
    s = Settings()
    with httpx.Client(base_url=f"http://{s.nacos_addr}/nacos", timeout=30) as client:
        p = Publisher(client, s)
        p.login()
        p.publish_all(args.label)


if __name__ == "__main__":
    main()
