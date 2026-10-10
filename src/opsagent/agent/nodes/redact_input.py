from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ..deps import Deps


def make_redact_input(deps: Deps):
    async def redact_input(state: dict) -> dict:
        question = deps.store.redactor().with_salt(state["run_id"]).redact_text(state["question"])
        # 每个新问题都是一个新的 Run：清空上一轮的消息和中间状态，只保留 history
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(question)],
            "question": question, "intent": None, "nodes": {}, "unresolved": [],
            "clarify_question": None, "clarify_count": 0, "assumptions": [], "skill": None,
            "step_count": 0, "reflect_rounds": 0, "reflect_retry": False, "evidence_ids": [],
            "tool_log": [], "partial_reasons": [], "report": None,
        }

    return redact_input
