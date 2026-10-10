def test_sdk_symbols_importable():
    """SdkNacosSource 依赖的 SDK 符号；SDK 升级后若被移动，这里会明确失败。"""
    from v2.nacos import ClientConfigBuilder, ConfigParam, NacosConfigService  # noqa: F401
    from v2.nacos.ai.model.ai_param import DownloadSkillParam, GetPromptParam  # noqa: F401
    from v2.nacos.ai.nacos_ai_service import NacosAIService  # noqa: F401


class _FakeAI:
    def __init__(self, prompt=None, zip_bytes=b"zip"):
        self.prompt, self.zip_bytes, self.skill_params = prompt, zip_bytes, []

    async def get_prompt(self, param):
        return self.prompt

    async def download_skill_zip(self, param):
        self.skill_params.append(param)
        return self.zip_bytes


class _FakeCfg:
    def __init__(self, text):
        self.text = text

    async def get_config(self, param):
        return self.text


def _source(ai=None, cfg=None):
    from opsagent.config import Settings
    from opsagent.nacos.source import SdkNacosSource

    s = SdkNacosSource(Settings(_env_file=None))
    s._ai, s._cfg = ai, cfg
    return s


async def test_sdk_source_maps_prompt_fields():
    from v2.nacos.ai.model.prompt.prompt import Prompt

    doc = await _source(ai=_FakeAI(Prompt(promptKey="k", version="1.0.0", template="hi"))).get_prompt("k", "stable")
    assert (doc.key, doc.version, doc.template) == ("k", "1.0.0", "hi")


async def test_sdk_source_prompt_without_template_raises():
    import pytest

    with pytest.raises(LookupError):
        await _source(ai=_FakeAI(None)).get_prompt("k", "stable")


async def test_sdk_source_uses_nacos_skill_name():
    ai = _FakeAI()
    assert await _source(ai=ai).get_skill_zip("http_5xx", "stable") == b"zip"
    assert ai.skill_params[0].skill_name == "http-5xx"
    assert ai.skill_params[0].label == "stable"


async def test_sdk_source_empty_config_raises():
    import pytest

    with pytest.raises(LookupError):
        await _source(cfg=_FakeCfg("")).get_config("x.yaml", "OPS_AGENT")
    assert await _source(cfg=_FakeCfg("a: 1")).get_config("x.yaml", "OPS_AGENT") == "a: 1"
