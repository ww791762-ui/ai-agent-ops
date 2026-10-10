# src/opsagent/agent/nodes/agent_step.py
from langchain_core.messages import SystemMessage

from ..deps import Deps
from ..prompting import format_history, render


def _context(state: dict, deps: Deps) -> str:
    intent = state.get("intent") or {}
    lines = [f"- 用户问题：{state['question']}"]
    for key in ("env", "time_from", "time_to", "symptom"):
        if intent.get(key):
            lines.append(f"- {key}：{intent[key]}")
    for role, node_id in state.get("nodes", {}).items():
        n = deps.topo.get(node_id)
        desc = f"：{n.description}" if n.description else ""
        lines.append(f"- {role} 节点：{node_id}（{n.name}，类型 {n.type}）{desc}")
    for a in state.get("assumptions", []):
        lines.append(f"- 默认假设：{a}")
    if state.get("history"):
        lines.append("- 之前的对话：\n" + format_history(state["history"]))
    return "\n".join(lines)


def make_agent_step(deps: Deps):
    async def agent_step(state: dict) -> dict:
        skill = deps.store.skill_by_md5(state["skill"]["md5"])  # Run 内固定 Skill 版本
        system = "\n\n".join([
            render(deps.store.prompt("ops.system").template, now=state["now"]),
            f"## 当前 Skill：{skill.meta.id}\n{skill.instructions}",
            f"## 已识别的上下文\n{_context(state, deps)}",
        ])
        tools = deps.gateway.registry.schemas(skill.meta.allowed_tools)
        ai = await deps.llm.chat([SystemMessage(system), *state["messages"]], tools)
        return {"messages": [ai]}

    return agent_step
