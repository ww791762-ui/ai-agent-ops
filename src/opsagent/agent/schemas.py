from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    intent: Literal["troubleshoot", "topology_query", "out_of_scope"]
    confidence: Literal["high", "medium", "low"] = "high"
    service: str | None = Field(None, description="用户提到的服务或组件名称，照抄原文")
    endpoint: str | None = Field(None, description="用户提到的接口名称或路径，照抄原文")
    env: str | None = Field(None, description="用户明确说出的环境，没说就留空")
    time_from: datetime | None = Field(None, description="开始时间，ISO 8601，带 +08:00")
    time_to: datetime | None = Field(None, description="结束时间，ISO 8601，带 +08:00")
    symptom: str | None = Field(None, description="一句话概括现象")
    reply: str | None = Field(None, description="仅 out_of_scope 时填写：给用户的回复")


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
