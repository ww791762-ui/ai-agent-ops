# src/opsagent/config.py
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSAGENT_", env_file=".env", extra="ignore")

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.modelarts-maas.com/openai/v1"
    llm_model: str = "glm-5.2"
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_s: float = 180  # glm-5.2 生成完整报告约 70 秒，60 秒会超时
    llm_structured_method: str = "function_calling"  # function_calling / json_schema / json_mode
    # 透传给模型接口的额外参数；glm-5.2 默认开启思考，耗时约为关闭时的 2–3 倍，诊断质量相当，所以默认关闭
    llm_extra_body: dict[str, Any] = Field(default_factory=lambda: {"thinking": {"type": "disabled"}})

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
