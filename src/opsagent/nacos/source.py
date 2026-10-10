import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from opsagent.config import Settings

from .skill import build_skill_zip, nacos_skill_name


@dataclass(frozen=True)
class PromptDoc:
    key: str
    version: str
    template: str

    @property
    def md5(self) -> str:
        return hashlib.md5(self.template.encode("utf-8")).hexdigest()


class NacosSource(Protocol):
    async def get_prompt(self, key: str, label: str) -> PromptDoc: ...
    async def get_skill_zip(self, name: str, label: str) -> bytes: ...
    async def get_config(self, data_id: str, group: str) -> str: ...


class SdkNacosSource:
    """通过 nacos-sdk-python（v2 API）读取本地 Nacos。

    行为以 docs/superpowers/plans/2026-10-10-spike-results.md 为准：
    - get_prompt 遇到不存在的 label 会静默回退到 latest，所以发布时必须保证 label 已绑定；
    - Skill 在 Nacos 中的名称是内部 id 把下划线换成连字符（见 nacos_skill_name）；
    - get_config 读不到配置时返回空字符串而不是抛异常。
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._ai = None
        self._cfg = None

    async def start(self) -> None:
        from v2.nacos import ClientConfigBuilder, NacosConfigService
        from v2.nacos.ai.nacos_ai_service import NacosAIService

        cfg = (ClientConfigBuilder().server_address(self._s.nacos_addr).namespace_id(self._s.nacos_namespace)
               .username(self._s.nacos_username).password(self._s.nacos_password.get_secret_value()).build())
        self._ai = await NacosAIService.create_ai_service(cfg)
        self._cfg = await NacosConfigService.create_config_service(cfg)

    async def close(self) -> None:
        for svc in (self._ai, self._cfg):
            if svc is not None and hasattr(svc, "shutdown"):
                await svc.shutdown()

    async def get_prompt(self, key: str, label: str) -> PromptDoc:
        from v2.nacos.ai.model.ai_param import GetPromptParam

        p = await self._ai.get_prompt(GetPromptParam(prompt_key=key, label=label))
        if p is None or p.template is None:
            raise LookupError(f"Nacos 中没有 Prompt {key}（label={label}）")
        return PromptDoc(key=key, version=str(p.version), template=p.template)

    async def get_skill_zip(self, name: str, label: str) -> bytes:
        from v2.nacos.ai.model.ai_param import DownloadSkillParam

        data = await self._ai.download_skill_zip(DownloadSkillParam(skill_name=nacos_skill_name(name), label=label))
        if not data:
            raise LookupError(f"Nacos 中没有 Skill {name}（label={label}）")
        return data

    async def get_config(self, data_id: str, group: str) -> str:
        from v2.nacos import ConfigParam

        text = await self._cfg.get_config(ConfigParam(data_id=data_id, group=group))
        if not text:
            raise LookupError(f"Nacos 中没有配置 {group}/{data_id}")
        return text


class SeedDirSource:
    """从仓库的 nacos_seed/ 目录读取，用于测试、冒烟和离线开发。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._manifest = yaml.safe_load((self._root / "manifest.yaml").read_text(encoding="utf-8"))

    async def get_prompt(self, key: str, label: str) -> PromptDoc:
        p = self._manifest["prompts"][key]
        return PromptDoc(key=key, version=str(p["version"]),
                         template=(self._root / p["file"]).read_text(encoding="utf-8"))

    async def get_skill_zip(self, name: str, label: str) -> bytes:
        return build_skill_zip(self._root / "skills" / name)

    async def get_config(self, data_id: str, group: str) -> str:
        for c in self._manifest["config"]:
            if c["data_id"] == data_id and c["group"] == group:
                return (self._root / c["file"]).read_text(encoding="utf-8")
        raise LookupError(f"seed 中没有配置 {group}/{data_id}")
