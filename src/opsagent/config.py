# src/opsagent/config.py
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSAGENT_", env_file=".env", extra="ignore")

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.modelarts-maas.com/openai/v1"
    llm_model: str = "deepseek-v4.1-flash"
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_s: float = 180  # 开启思考后生成完整报告可能超过 60 秒
    # function_calling / json_schema / json_mode；deepseek-v4.1-flash 的 json_schema 不可用（JSON 被包在 ```json 代码块里）
    llm_structured_method: str = "function_calling"
    # 思考模式：默认关闭（更快，冒烟场景质量足够）；处理复杂问题时设为 true
    llm_thinking: bool = False
    # 透传给模型接口的额外参数，与 thinking 合并，同名键以这里为准
    llm_extra_body: dict[str, Any] = Field(default_factory=dict)

    nacos_addr: str = "127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_username: str = ""
    nacos_password: SecretStr = SecretStr("")
    nacos_label: str = "stable"
    nacos_poll_s: int = 60
    nacos_mode: Literal["sdk", "seed"] = "sdk"  # sdk：读取 Nacos；seed：直接读取 nacos_seed/ 目录（离线开发用）

    db_url: str = "postgresql+psycopg://opsagent:opsagent@localhost:5432/opsagent"
    cache_dir: Path = Path(".cache/nacos")

    mock_scenario: str = "b_pay_slow"
    scenarios_dir: Path = Path("fixtures/scenarios")
    tool_timeout_s: float = 30
    tool_retries: int = 2
    clarify_timeout_min: int = 30

    @property
    def checkpoint_db_url(self) -> str:
        """LangGraph 的 AsyncPostgresSaver 需要不带 SQLAlchemy 驱动后缀的 URL。"""
        return self.db_url.replace("postgresql+psycopg://", "postgresql://", 1)
