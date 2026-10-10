import yaml
from pydantic import BaseModel, Field


class RedactionRules(BaseModel):
    block_fields: list[str] = Field(default_factory=list)          # 字段名，大小写不敏感，等于或以其结尾
    block_patterns: dict[str, str] = Field(default_factory=dict)   # 类型名 -> 正则，按顺序执行
    mask_patterns: dict[str, str] = Field(default_factory=dict)    # phone / id_card / bank_card / email
    tokenize_fields: list[str] = Field(default_factory=list)


def load_rules(text: str) -> RedactionRules:
    return RedactionRules.model_validate(yaml.safe_load(text) or {})
