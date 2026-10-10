import pytest

from opsagent.nacos.cache import FileCache
from opsagent.nacos.source import PromptDoc
from opsagent.nacos.store import REDACTION_DATA_ID, REDACTION_GROUP, ConfigStore, StoreUnavailable
from tests.helpers import TOOL_IDS, DictSource, make_skill_zip

KEYS = ("ops.system", "ops.intent")
RULES = "block_patterns:\n  bearer: '(?i)bearer\\s+\\S+'\n"


def skill_meta(version: str, tools=("logs.search",)) -> dict:
    return {"id": "http_5xx", "version": version, "intents": ["troubleshoot"], "allowed_tools": list(tools)}


def source(version: str = "1.0.0") -> DictSource:
    src = DictSource()
    for k in KEYS:
        src.prompts[k] = PromptDoc(key=k, version=version, template=f"{k} v{version}")
    src.skills["http_5xx"] = make_skill_zip(skill_meta(version))
    src.configs[(REDACTION_DATA_ID, REDACTION_GROUP)] = RULES
    return src


def store(src: DictSource, tmp_path) -> ConfigStore:
    return ConfigStore(src, FileCache(tmp_path), "stable", TOOL_IDS, prompt_keys=KEYS, skill_names=("http_5xx",))


async def test_load_and_versions(tmp_path):
    s = store(source(), tmp_path)
    await s.load()
    assert s.prompt("ops.system").template == "ops.system v1.0.0"
    assert s.skill("http_5xx").meta.version == "1.0.0"
    assert [k.meta.id for k in s.skills()] == ["http_5xx"]
    v = s.versions()
    assert v["prompts"]["ops.intent"]["version"] == "1.0.0"
    assert v["skills"]["http_5xx"]["md5"] == s.skill("http_5xx").md5
    assert "[REDACTED:bearer]" in s.redactor().redact_text("Bearer abc")


async def test_startup_uses_cache_when_nacos_down(tmp_path):  # T14
    await store(source(), tmp_path).load()
    down = source()
    down.down = True
    s = store(down, tmp_path)
    await s.load()
    assert s.prompt("ops.system").version == "1.0.0"
    assert s.skill("http_5xx").meta.version == "1.0.0"


async def test_startup_fails_without_cache(tmp_path):
    down = source()
    down.down = True
    with pytest.raises(StoreUnavailable):
        await store(down, tmp_path).load()


async def test_invalid_new_skill_keeps_previous(tmp_path):  # T15
    src = source()
    s = store(src, tmp_path)
    await s.load()
    src.skills["http_5xx"] = make_skill_zip(skill_meta("2.0.0", tools=("shell.exec",)))
    await s.refresh()
    assert s.skill("http_5xx").meta.version == "1.0.0"


async def test_refresh_picks_new_versions_and_keeps_old_by_md5(tmp_path):
    src = source()
    s = store(src, tmp_path)
    await s.load()
    old_md5 = s.skill("http_5xx").md5
    src.prompts["ops.system"] = PromptDoc(key="ops.system", version="2.0.0", template="new")
    src.skills["http_5xx"] = make_skill_zip(skill_meta("2.0.0"))
    await s.refresh()
    assert s.prompt("ops.system").version == "2.0.0"
    assert s.skill("http_5xx").meta.version == "2.0.0"
    assert s.skill_by_md5(old_md5).meta.version == "1.0.0"  # 进行中的 Run 仍可取到旧版本


async def test_refresh_when_down_keeps_current(tmp_path):
    src = source()
    s = store(src, tmp_path)
    await s.load()
    src.down = True
    await s.refresh()
    assert s.prompt("ops.system").version == "1.0.0"


@pytest.mark.parametrize("bad", ["", "block_fields: [password]\n", "block_patterns: {}\n"])
async def test_rules_without_block_patterns_rejected_on_refresh(tmp_path, bad):
    src = source()
    s = store(src, tmp_path)
    await s.load()
    src.configs[(REDACTION_DATA_ID, REDACTION_GROUP)] = bad
    await s.refresh()
    assert "[REDACTED:bearer]" in s.redactor().redact_text("Bearer abc")
    # 不合法的规则也不能覆盖本地缓存
    fresh = source()
    fresh.down = True
    s2 = store(fresh, tmp_path)
    await s2.load()
    assert "[REDACTED:bearer]" in s2.redactor().redact_text("Bearer abc")


async def test_rules_without_block_patterns_at_startup_uses_cache(tmp_path):
    await store(source(), tmp_path).load()
    src = source()
    src.configs[(REDACTION_DATA_ID, REDACTION_GROUP)] = "block_fields: [password]\n"
    s = store(src, tmp_path)
    await s.load()
    assert "[REDACTED:bearer]" in s.redactor().redact_text("Bearer abc")


async def test_rules_without_block_patterns_and_no_cache_fails(tmp_path):
    src = source()
    src.configs[(REDACTION_DATA_ID, REDACTION_GROUP)] = "block_patterns: {}\n"
    with pytest.raises(StoreUnavailable):
        await store(src, tmp_path).load()
