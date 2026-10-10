# src/opsagent/agent/transcript.py
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_CLIP = 4000


def _clip(text: str) -> str:
    return text if len(text) <= _CLIP else text[:_CLIP] + "…（已截断）"


def render_transcript(state: dict) -> str:
    """把当前 Run 的过程渲染为纯文本，供反思和报告使用（避免 tool_call 配对问题）。"""
    lines = [f"用户问题：{state['question']}",
             f"识别结果：{json.dumps(state.get('intent'), ensure_ascii=False)}",
             f"已解析节点：{json.dumps(state.get('nodes', {}), ensure_ascii=False)}"]
    if state.get("assumptions"):
        lines.append("默认假设：" + "；".join(state["assumptions"]))
    for m in state.get("messages", []):
        if isinstance(m, HumanMessage):
            lines.append(f"[用户/系统] {m.content}")
        elif isinstance(m, AIMessage):
            if m.content:
                lines.append(f"[Agent] {m.content}")
            for tc in m.tool_calls:
                lines.append(f"[调用工具] {tc['name']} {json.dumps(tc['args'], ensure_ascii=False)}")
        elif isinstance(m, ToolMessage):
            lines.append(f"[工具结果] {_clip(str(m.content))}")
    return "\n".join(lines)
