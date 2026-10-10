from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class Turn(TypedDict):
    question: str
    answer: str


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]   # 仅当前 Run 的消息
    question: str                  # 已脱敏的用户问题
    run_id: str
    now: str                       # ISO 8601，Run 开始的时间
    history: list[Turn]            # 同一会话之前的问答（L1 记忆），最多 5 轮
    intent: dict | None            # IntentResult.model_dump(mode="json")
    nodes: dict[str, str]          # {"service": node_id, "endpoint": node_id}
    unresolved: list[str]          # 追问之后仍然无法确定的实体
    clarify_question: str | None
    clarify_count: int
    assumptions: list[str]
    skill: dict | None             # {"id", "version", "md5"}
    step_count: int
    reflect_rounds: int
    reflect_retry: bool
    evidence_ids: list[str]
    tool_log: list[dict]           # {"fn", "args_key", "tool", "node_id", "status", "evidence_id"}
    partial_reasons: list[str]
    report: dict | None
