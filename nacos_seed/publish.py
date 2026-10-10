"""把 nacos_seed/ 中的 Prompt、Skill、脱敏规则发布到 Nacos，并打上 label。

用法：uv run python -m nacos_seed.publish [--label stable]
接口路径和参数以 docs/superpowers/plans/2026-10-10-spike-results.md 的结论为准：
- Prompt：POST draft（targetVersion）-> POST force-publish -> PUT labels（labels 为 JSON 字符串）。
  旧接口 POST /v3/admin/ai/prompt 只做到 draft+submit（reviewing），SDK 读不到。
- Skill：单个 POST upload（multipart，targetVersion）-> POST force-publish -> PUT labels。
  upload/batch 不支持 targetVersion（版本只来自 SKILL.md frontmatter，否则为 0.0.1）。
  PUT labels 会整体替换 label 表（包括 latest），所以先读出现有 label 再合并。
- Skill 名称只允许小写字母、数字和连字符，上传时把 SKILL.md 的 name 换成 nacos_skill_name(id)。
- 同一版本已存在时不重复上传内容（Skill upload 遇到同版本会自动升 patch 版本）。
  因此修改 Prompt / Skill 内容后**必须同时升版本号**（manifest.yaml / skill.yaml），否则发布会跳过、Nacos 仍是旧内容。
- label 采用读取-合并-写回，不要并发运行多个发布进程。
"""
import argparse
import io
import json
import re
import zipfile
from pathlib import Path

import httpx
import yaml

from opsagent.config import Settings
from opsagent.nacos.skill import nacos_skill_name

ROOT = Path(__file__).parent
LOGIN = "/v3/auth/user/login"
PROMPT_DETAIL = ("GET", "/v3/admin/ai/prompt/governance")
PROMPT_DRAFT = ("POST", "/v3/admin/ai/prompt/draft")
PROMPT_PUBLISH = ("POST", "/v3/admin/ai/prompt/force-publish")
PROMPT_LABELS = ("PUT", "/v3/admin/ai/prompt/labels")
SKILL_DETAIL = ("GET", "/v3/admin/ai/skills")
SKILL_UPLOAD = ("POST", "/v3/admin/ai/skills/upload")
SKILL_PUBLISH = ("POST", "/v3/admin/ai/skills/force-publish")
SKILL_LABELS = ("PUT", "/v3/admin/ai/skills/labels")
CONFIG_PUBLISH = ("POST", "/v3/admin/cs/config")
ONLINE = "online"


def skill_upload_zip(skill_id: str) -> bytes:
    """打包单个 Skill 用于上传：目录名和 SKILL.md frontmatter 的 name 都换成 Nacos 合法名称。"""
    skill_dir = ROOT / "skills" / skill_id
    name = nacos_skill_name(skill_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if not f.is_file():
                continue
            data = f.read_bytes()
            if f.name == "SKILL.md":
                data = _rename_frontmatter(data.decode("utf-8"), name).encode("utf-8")
            zf.writestr(f"{name}/{f.relative_to(skill_dir).as_posix()}", data)
    return buf.getvalue()


_FRONTMATTER = re.compile(r"^\ufeff?---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)


def _rename_frontmatter(text: str, name: str) -> str:
    """把 frontmatter 的 name 换成 Nacos 名称，并去掉 version（Nacos 会优先用它而不是 targetVersion）。"""
    m = _FRONTMATTER.match(text)
    if not m:
        return f"---\nname: {name}\n---\n{text}"
    lines = [ln for ln in m.group(1).splitlines()
             if not re.match(r"(?:name|version)\s*:", ln)]
    fm = "\n".join([f"name: {name}", *lines])
    return f"---\n{fm}\n---\n{text[m.end():]}"


def _version_status(detail: dict | None, versions_key: str, version: str) -> str | None:
    for v in (detail or {}).get(versions_key) or []:
        if isinstance(v, dict) and v.get("version") == version:
            return v.get("status")
    return None


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
        params = {"accessToken": self._token, **kw.pop("params", {})}
        r = self._c.request(method, path, params=params, **kw)
        r.raise_for_status()
        body = r.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"{method} {path} 失败: {body}")
        return body

    def _detail(self, endpoint: tuple[str, str], params: dict) -> dict | None:
        """读取资源详情；资源不存在（404）时返回 None。"""
        method, path = endpoint
        r = self._c.request(method, path, params={"accessToken": self._token, **params})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json().get("data")
        return data if isinstance(data, dict) else None

    def publish_prompt(self, ns: str, key: str, version: str, template: str, label: str) -> None:
        ident = {"namespaceId": ns, "promptKey": key}
        status = _version_status(self._detail(PROMPT_DETAIL, ident), "versionDetails", version)
        if status is None:
            self._call(PROMPT_DRAFT, data={**ident, "targetVersion": version, "template": template,
                                           "commitMsg": "seed"})
        else:
            print(f"Prompt {key} {version} 已存在（{status}），不重新上传内容")
        if status != ONLINE:
            self._call(PROMPT_PUBLISH, data={**ident, "version": version, "updateLatestLabel": "true"})
        labels = dict((self._detail(PROMPT_DETAIL, ident) or {}).get("labels") or {})
        labels[label] = version
        self._call(PROMPT_LABELS, data={**ident, "labels": json.dumps(labels)})

    def publish_skill(self, ns: str, skill_id: str, version: str, label: str) -> None:
        ident = {"namespaceId": ns, "skillName": nacos_skill_name(skill_id)}
        status = _version_status(self._detail(SKILL_DETAIL, ident), "versions", version)
        if status is None:
            self._call(SKILL_UPLOAD, data={"namespaceId": ns, "overwrite": "true", "targetVersion": version,
                                           "commitMsg": "seed"},
                       files={"file": (f"{ident['skillName']}.zip", skill_upload_zip(skill_id), "application/zip")})
        else:
            print(f"Skill {skill_id} {version} 已存在（{status}），不重新上传内容")
        if status != ONLINE:
            self._call(SKILL_PUBLISH, data={**ident, "version": version, "updateLatestLabel": "true"})
        labels = dict((self._detail(SKILL_DETAIL, ident) or {}).get("labels") or {})
        labels[label] = version
        self._call(SKILL_LABELS, data={**ident, "labels": json.dumps(labels)})

    def publish_all(self, label: str) -> None:
        manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
        ns = self._s.nacos_namespace
        for key, p in manifest["prompts"].items():
            version = str(p["version"])
            self.publish_prompt(ns, key, version, (ROOT / p["file"]).read_text(encoding="utf-8"), label)
            print(f"Prompt {key} {version} -> {label}")
        for skill_id in manifest["skills"]:
            meta = yaml.safe_load((ROOT / "skills" / skill_id / "skill.yaml").read_text(encoding="utf-8"))
            version = str(meta["version"])
            self.publish_skill(ns, skill_id, version, label)
            print(f"Skill {skill_id}（Nacos 名称 {nacos_skill_name(skill_id)}）{version} -> {label}")
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
