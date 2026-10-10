import hashlib
import re
from collections import Counter
from typing import Any

from .rules import RedactionRules

_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = "10X98765432"


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _id_card_ok(value: str) -> bool:
    v = value.upper()
    if len(v) != 18 or not v[:17].isdigit():
        return False
    return _ID_CHECK[sum(int(c) * w for c, w in zip(v[:17], _ID_WEIGHTS)) % 11] == v[17]


_VALIDATORS = {"id_card": _id_card_ok, "bank_card": _luhn_ok}


def _mask(kind: str, value: str) -> str:
    if kind == "phone":
        return value[:3] + "****" + value[-4:]
    if kind == "email":
        name, _, domain = value.partition("@")
        return name[:1] + "***@" + domain
    if kind in ("id_card", "bank_card"):
        return value[:4] + "*" * (len(value) - 8) + value[-4:]
    return "*" * len(value)


class Redactor:
    def __init__(self, rules: RedactionRules, salt: str = "") -> None:
        self._rules = rules
        self._salt = salt
        self._block = [(n, re.compile(p)) for n, p in rules.block_patterns.items()]
        self._mask = [(n, re.compile(p)) for n, p in rules.mask_patterns.items()]
        self._block_fields = [f.lower() for f in rules.block_fields]
        self._tok_fields = {f.lower() for f in rules.tokenize_fields}
        self._tok_text = (
            re.compile(r"(?i)\b(" + "|".join(map(re.escape, self._tok_fields)) + r")\s*[=:]\s*\"?([\w-]+)")
            if self._tok_fields else None
        )

    def with_salt(self, salt: str) -> "Redactor":
        return Redactor(self._rules, salt)

    def tokenize(self, kind: str, value: str) -> str:
        digest = hashlib.sha256(f"{self._salt}:{kind}:{value}".encode()).hexdigest()[:4]
        return f"{kind.removesuffix('_id')}_{digest}"

    def redact_text(self, text: str, stats: Counter | None = None) -> str:
        stats = stats if stats is not None else Counter()
        for name, rx in self._block:
            text, n = rx.subn(f"[REDACTED:{name}]", text)
            if n:
                stats[name] += n
        for name, rx in self._mask:
            check = _VALIDATORS.get(name)

            def repl(m: re.Match, name: str = name, check=check) -> str:
                value = m.group(0)
                if check and not check(value):
                    return value
                stats[name] += 1
                return _mask(name, value)

            text = rx.sub(repl, text)
        if self._tok_text:
            def tok(m: re.Match) -> str:
                stats["tokenize:" + m.group(1).lower()] += 1
                prefix = m.group(0)[: m.start(2) - m.start(0)]
                return prefix + self.tokenize(m.group(1).lower(), m.group(2))

            text = self._tok_text.sub(tok, text)
        return text

    def redact_obj(self, obj: Any, stats: Counter | None = None) -> Any:
        stats = stats if stats is not None else Counter()
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                key = str(k).lower()
                if v not in (None, "") and any(key == f or key.endswith(f) for f in self._block_fields):
                    out[k] = f"[REDACTED:{key}]"
                    stats["field:" + key] += 1
                elif v not in (None, "") and key in self._tok_fields:
                    out[k] = self.tokenize(key, str(v))
                    stats["tokenize:" + key] += 1
                else:
                    out[k] = self.redact_obj(v, stats)
            return out
        if isinstance(obj, list):
            return [self.redact_obj(v, stats) for v in obj]
        if isinstance(obj, str):
            return self.redact_text(obj, stats)
        return obj
