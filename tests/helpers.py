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
