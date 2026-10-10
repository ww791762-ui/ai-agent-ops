def test_sdk_symbols_importable():
    """SdkNacosSource 依赖的 SDK 符号；SDK 升级后若被移动，这里会明确失败。"""
    from v2.nacos import ClientConfigBuilder, ConfigParam, NacosConfigService  # noqa: F401
    from v2.nacos.ai.model.ai_param import DownloadSkillParam, GetPromptParam  # noqa: F401
    from v2.nacos.ai.nacos_ai_service import NacosAIService  # noqa: F401
