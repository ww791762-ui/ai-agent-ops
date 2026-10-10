from langgraph.graph import END, START, StateGraph

from .deps import Deps
from .nodes.agent_step import make_agent_step
from .nodes.clarify import make_clarify
from .nodes.finalize import make_finalize
from .nodes.intent import make_intent
from .nodes.redact_input import make_redact_input
from .nodes.reflect import make_reflect
from .nodes.route_skill import make_route_skill
from .nodes.tools import make_tools
from .state import AgentState


def after_intent(state: dict) -> str:
    if (state.get("intent") or {}).get("intent") == "out_of_scope":
        return "finalize"
    if state.get("clarify_question"):
        return "clarify"
    if state.get("unresolved"):
        return "finalize"
    return "route_skill"


def after_reflect(state: dict) -> str:
    return "agent" if state.get("reflect_retry") else "finalize"


def build_graph(deps: Deps, checkpointer):
    def after_agent(state: dict) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            max_steps = deps.store.skill_by_md5(state["skill"]["md5"]).meta.max_steps
            return "tools" if state.get("step_count", 0) < max_steps else "finalize"
        return "reflect"

    g = StateGraph(AgentState)
    g.add_node("redact_input", make_redact_input(deps))
    g.add_node("intent", make_intent(deps))
    g.add_node("clarify", make_clarify(deps))
    g.add_node("route_skill", make_route_skill(deps))
    g.add_node("agent", make_agent_step(deps))
    g.add_node("tools", make_tools(deps))
    g.add_node("reflect", make_reflect(deps))
    g.add_node("finalize", make_finalize(deps))

    g.add_edge(START, "redact_input")
    g.add_edge("redact_input", "intent")
    g.add_conditional_edges("intent", after_intent, ["clarify", "route_skill", "finalize"])
    g.add_edge("clarify", "intent")
    g.add_edge("route_skill", "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "reflect", "finalize"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("reflect", after_reflect, ["agent", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
