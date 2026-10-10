import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_JSON_TAIL = re.compile(r'\s*"\s*}\s*$')


class IntentResult(BaseModel):
    intent: Literal["troubleshoot", "topology_query", "out_of_scope"]
    confidence: Literal["high", "medium", "low"] = "high"
    service: str | None = Field(None, description="用户提到的服务或组件名称，照抄原文")
    endpoint: str | None = Field(None, description="用户提到的接口名称或路径，照抄原文")
    env: str | None = Field(None, description="用户明确说出的环境，没说就留空")
    time_from: datetime | None = Field(None, description="开始时间，Asia/Shanghai 本地时间，不带时区，如 2026-10-09T20:00:00")
    time_to: datetime | None = Field(None, description="结束时间，Asia/Shanghai 本地时间，不带时区")
    symptom: str | None = Field(None, description="一句话概括现象")
    reply: str | None = Field(None, description="仅 out_of_scope 时填写：给用户的回复")

    @field_validator("time_from", "time_to")
    @classmethod
    def _local_wall_clock(cls, v: datetime | None) -> datetime | None:
        # 模型常把本地时间标成 UTC 或省略时区，所以忽略模型给出的偏移，一律按 Asia/Shanghai 墙上时间解释
        return v.replace(tzinfo=LOCAL_TZ) if v else v

    @field_validator("reply")
    @classmethod
    def _unescape_reply(cls, v: str | None) -> str | None:
        # 模型在 function call 参数里会把换行多转义一次，并偶尔残留 JSON 结尾的 "}
        if not v:
            return v
        if "\n" not in v:
            v = v.replace("\\n", "\n")
        if v.count('"') % 2 == 1:  # 引号不成对才是残留
            v = _JSON_TAIL.sub("", v)
        return v


class Finding(BaseModel):
    fact: str
    evidence_ids: list[str] = Field(default_factory=list)


class HopStatus(BaseModel):
    node: str
    status: Literal["normal", "abnormal", "unknown"]
    observation: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    cause: str
    support: list[str] = Field(default_factory=list)
    against: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class Report(BaseModel):
    summary: str
    paths: list[list[str]] = Field(default_factory=list)
    hops: list[HopStatus] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    needs_human: bool = False
    assumptions: list[str] = Field(default_factory=list)
    dropped_claims: int = 0


class ReflectVerdict(BaseModel):
    ok: bool
    issues: list[str] = Field(default_factory=list)
