from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from ..deps import Deps


def make_clarify(deps: Deps):
    async def clarify(state: dict) -> dict:
        question = state["clarify_question"]
        answer = interrupt({"question": question})  # 恢复时，返回 Command(resume=...) 中的值
        answer = deps.store.redactor().with_salt(state["run_id"]).redact_text(str(answer))
        return {"messages": [AIMessage(question), HumanMessage(answer)],
                "clarify_count": state.get("clarify_count", 0) + 1, "clarify_question": None}

    return clarify
