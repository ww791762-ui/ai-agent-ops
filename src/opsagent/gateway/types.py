import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

_WRAPPER_TAG = re.compile(r"<(/?)untrusted_data>", re.IGNORECASE)

ToolStatus = Literal["ok", "empty", "truncated", "denied", "backend_error"]


class ToolCallReq(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


@dataclass
class RunContext:
    run_id: str
    allowed_tools: set[str] = field(default_factory=set)


class ToolResult(BaseModel):
    status: ToolStatus
    data: Any = None
    evidence_id: str | None = None
    error: str | None = None
    redaction_stats: dict[str, int] = Field(default_factory=dict)

    def to_model_content(self) -> str:
        payload = json.dumps(self.model_dump(exclude={"redaction_stats"}), ensure_ascii=False, default=str)
        payload = _WRAPPER_TAG.sub(lambda m: f"&lt;{m.group(1)}untrusted_data&gt;", payload)
        return f"<untrusted_data>\n{payload}\n</untrusted_data>"


class AdapterResult(BaseModel):
    status: Literal["ok", "empty", "truncated"]
    data: Any = None


class TransientError(Exception):
    """超时、429、5xx 等可以重试的后端错误。"""


class EvidenceRecorder(Protocol):
    async def record(self, *, run_id: str, tool: str, args: dict, status: str, data: Any,
                     redaction_stats: dict, duration_ms: int, error: str | None,
                     make_evidence: bool) -> str | None: ...


class InMemoryRecorder:
    """测试和冒烟用：证据 ID 依次为 ev-1、ev-2……"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.evidences: dict[str, Any] = {}

    async def record(self, *, run_id: str, tool: str, args: dict, status: str, data: Any,
                     redaction_stats: dict, duration_ms: int, error: str | None,
                     make_evidence: bool) -> str | None:
        evidence_id = f"ev-{len(self.evidences) + 1}" if make_evidence else None
        if evidence_id:
            self.evidences[evidence_id] = data
        self.calls.append({"run_id": run_id, "tool": tool, "args": args, "status": status,
                           "error": error, "evidence_id": evidence_id})
        return evidence_id
