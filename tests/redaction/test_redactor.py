from collections import Counter
from pathlib import Path

import pytest

from opsagent.redaction.redactor import Redactor
from opsagent.redaction.rules import load_rules

RULES = load_rules(Path("nacos_seed/redaction.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def r() -> Redactor:
    return Redactor(RULES, salt="run-1")


@pytest.mark.parametrize("text,kind,leak", [
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig123", "bearer", "eyJhbGci"),
    ("jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig123 end", "jwt", "eyJhbGci"),
    ("GET /b/pay?token=abcd1234&x=1", "url_secret", "abcd1234"),
    ("password=S3cret! next", "kv_secret", "S3cret"),
    ("jdbc:mysql://pay_user:S3cret@db-pay:3306/pay", "db_password", "S3cret"),
    ("key AKIAABCDEFGHIJKLMNOP x", "aws_ak", "AKIAABCDEFGHIJKLMNOP"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----", "private_key", "MIIabc"),
])
def test_block_patterns(r, text, kind, leak):
    out = r.redact_text(text)
    assert f"[REDACTED:{kind}]" in out
    assert leak not in out


def test_mask_phone_email(r):
    out = r.redact_text("phone=13812341234 mail=zhangsan@example.com")
    assert "138****1234" in out
    assert "z***@example.com" in out


def test_id_card_checksum(r):
    out = r.redact_text("valid 11010519491231002X invalid 110105194912310021")
    assert "1101" + "*" * 10 + "002X" in out
    assert "110105194912310021" in out  # 校验位错误，不掩码


def test_bank_card_luhn(r):
    out = r.redact_text("ok 4111111111111111 bad 4111111111111112")
    assert "4111********1111" in out
    assert "4111111111111112" in out


def test_tokenize_text_consistent_within_salt(r):
    out = r.redact_text("user_id=88231 again user_id=88231 other user_id=1")
    assert "88231" not in out
    tok = r.tokenize("user_id", "88231")
    assert out.count(tok) == 2
    assert Redactor(RULES, salt="run-2").tokenize("user_id", "88231") != tok


def test_redact_obj_fields_and_stats(r):
    stats = Counter()
    out = r.redact_obj({
        "Authorization": "abc", "access_token": "xyz", "player_id": "p-1",
        "nested": [{"msg": "call 13812341234"}], "count": 3,
    }, stats)
    assert out["Authorization"] == "[REDACTED:authorization]"
    assert out["access_token"] == "[REDACTED:access_token]"
    assert out["player_id"].startswith("player_")
    assert out["nested"][0]["msg"] == "call 138****1234"
    assert out["count"] == 3
    assert stats["phone"] == 1 and stats["field:authorization"] == 1
