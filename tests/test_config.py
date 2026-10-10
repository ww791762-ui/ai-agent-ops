from opsagent.config import Settings
from opsagent.ids import new_id


def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai_compatible"
    assert s.llm_base_url == "https://api.modelarts-maas.com/openai/v1"
    assert s.llm_model == "glm-5.2"
    assert s.nacos_namespace == "public"
    assert s.nacos_label == "stable"


def test_env_override_and_checkpoint_url(monkeypatch):
    monkeypatch.setenv("OPSAGENT_LLM_MODEL", "other-model")
    monkeypatch.setenv("OPSAGENT_DB_URL", "postgresql+psycopg://u:p@h:5432/db")
    s = Settings(_env_file=None)
    assert s.llm_model == "other-model"
    assert s.checkpoint_db_url == "postgresql://u:p@h:5432/db"


def test_secret_not_in_repr(monkeypatch):
    monkeypatch.setenv("OPSAGENT_LLM_API_KEY", "sk-very-secret")
    assert "sk-very-secret" not in repr(Settings(_env_file=None))


def test_new_id_prefix_and_uniqueness():
    a, b = new_id("run"), new_id("run")
    assert a.startswith("run-") and a != b
