import asyncio
import logging

from opsagent.redaction.redactor import Redactor
from opsagent.redaction.rules import RedactionRules, load_rules

from .cache import FileCache
from .skill import Skill, SkillError, parse_skill_zip
from .source import NacosSource, PromptDoc

log = logging.getLogger(__name__)

PROMPT_KEYS = ("ops.system", "ops.intent", "ops.reflect.inrun", "ops.report")
SKILL_NAMES = ("http_5xx", "topology_qa", "generic_troubleshoot")
REDACTION_DATA_ID = "ops-agent-redaction.yaml"
REDACTION_GROUP = "OPS_AGENT"


class StoreUnavailable(RuntimeError):
    pass


def _parse_rules(text: str) -> RedactionRules:
    """解析脱敏规则；缺少核心内容（block_patterns 为空）的文档视为不合法，避免静默关闭脱敏。"""
    rules = load_rules(text)
    if not rules.block_patterns:
        raise ValueError("脱敏规则缺少 block_patterns")
    Redactor(rules)  # 正则必须都能编译
    return rules


class ConfigStore:
    def __init__(self, source: NacosSource, cache: FileCache, label: str, known_tools: set[str],
                 prompt_keys: tuple[str, ...] = PROMPT_KEYS, skill_names: tuple[str, ...] = SKILL_NAMES) -> None:
        self._source = source
        self._cache = cache
        self._label = label
        self._known_tools = set(known_tools)
        self._prompt_keys = prompt_keys
        self._skill_names = skill_names
        self._prompts: dict[str, PromptDoc] = {}
        self._skills: dict[str, Skill] = {}
        self._skills_by_md5: dict[str, Skill] = {}
        self._redactor: Redactor | None = None

    # ---- 加载 ----
    async def load(self) -> None:
        await self._sync(strict=True)

    async def refresh(self) -> None:
        try:
            await self._sync(strict=False)
        except Exception:
            log.exception("刷新 Nacos 配置失败，继续使用当前版本")

    async def run_refresh_loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            await self.refresh()

    async def _sync(self, strict: bool) -> None:
        for key in self._prompt_keys:
            await self._sync_prompt(key, strict)
        for name in self._skill_names:
            await self._sync_skill(name, strict)
        await self._sync_redaction(strict)

    def _fallback(self, kind: str, key: str, strict: bool, err: Exception) -> tuple[bytes, dict] | None:
        cached = self._cache.load(kind, key)
        if cached is None:
            if strict:
                raise StoreUnavailable(f"{kind} {key} 无法从 Nacos 获取，且没有本地缓存: {err}") from err
            return None
        log.warning("%s %s 从 Nacos 获取失败，使用本地缓存: %s", kind, key, err)
        return cached

    async def _sync_prompt(self, key: str, strict: bool) -> None:
        try:
            doc = await self._source.get_prompt(key, self._label)
        except Exception as e:
            if key in self._prompts:
                log.warning("Prompt %s 刷新失败，保留当前版本: %s", key, e)
                return
            cached = self._fallback("prompt", key, strict, e)
            if cached is None:
                return
            data, meta = cached
            doc = PromptDoc(key=key, version=meta.get("version", "cached"), template=data.decode("utf-8"))
        else:
            self._cache.save("prompt", key, doc.template.encode("utf-8"), {"version": doc.version})
        self._prompts[key] = doc

    async def _sync_skill(self, name: str, strict: bool) -> None:
        try:
            data = await self._source.get_skill_zip(name, self._label)
            skill = self._parse(name, data)
        except Exception as e:
            if name in self._skills:
                log.warning("Skill %s 刷新失败或新版本不合法，保留当前版本: %s", name, e)
                return
            cached = self._fallback("skill", name, strict, e)
            if cached is None:
                return
            skill = self._parse(name, cached[0])
        else:
            self._cache.save("skill", name, data, {"version": skill.meta.version})
        self._skills[name] = skill
        self._skills_by_md5[skill.md5] = skill

    def _parse(self, name: str, data: bytes) -> Skill:
        skill = parse_skill_zip(data, self._known_tools)
        if skill.meta.id != name:
            raise SkillError(f"Skill 包的 id={skill.meta.id} 与名称 {name} 不一致")
        return skill

    async def _sync_redaction(self, strict: bool) -> None:
        try:
            text = await self._source.get_config(REDACTION_DATA_ID, REDACTION_GROUP)
            rules = _parse_rules(text)
        except Exception as e:
            if self._redactor is not None:
                log.warning("脱敏规则刷新失败，保留当前规则: %s", e)
                return
            cached = self._fallback("config", REDACTION_DATA_ID, strict, e)
            if cached is None:
                return
            try:
                rules = _parse_rules(cached[0].decode("utf-8"))
            except Exception as ce:
                if strict:
                    raise StoreUnavailable(f"脱敏规则不可用，本地缓存也不合法: {ce}") from ce
                return
        else:
            self._cache.save("config", REDACTION_DATA_ID, text.encode("utf-8"), {})
        self._redactor = Redactor(rules)

    # ---- 读取 ----
    def prompt(self, key: str) -> PromptDoc:
        return self._prompts[key]

    def skill(self, name: str) -> Skill:
        return self._skills[name]

    def skill_by_md5(self, md5: str) -> Skill:
        return self._skills_by_md5[md5]

    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def redactor(self) -> Redactor:
        if self._redactor is None:
            raise StoreUnavailable("脱敏规则尚未加载")
        return self._redactor

    def versions(self) -> dict:
        return {
            "prompts": {k: {"version": p.version, "md5": p.md5} for k, p in self._prompts.items()},
            "skills": {k: {"version": s.meta.version, "md5": s.md5} for k, s in self._skills.items()},
        }
