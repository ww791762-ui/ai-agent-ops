# src/opsagent/config.py
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSAGENT_", env_file=".env", extra="ignore")

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.modelarts-maas.com/openai/v1"
    llm_model: str = "glm-5.2"
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_s: float = 60
    llm_structured_method: str = "function_calling"  # function_calling / json_schema / json_mode

    nacos_addr: str = "127.0.0.1:8848"
    nacos_namespace: str = "public"
    nacos_username: str = ""
    nacos_password: SecretStr = SecretStr("")
    nacos_label: str = "stable"
    nacos_poll_s: int = 60

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
