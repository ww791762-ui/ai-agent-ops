# src/opsagent/agent/nodes/tools.py
import json

from langchain_core.messages import ToolMessage

from opsagent.gateway.types import RunContext, ToolCallReq

from ..deps import Deps


def make_tools(deps: Deps):
    async def tools(state: dict) -> dict:
        ai = state["messages"][-1]
        skill = deps.store.skill_by_md5(state["skill"]["md5"])
        ctx = RunContext(run_id=state["run_id"], allowed_tools=set(skill.meta.allowed_tools))
        evidence_ids = list(state.get("evidence_ids", []))
        tool_log = list(state.get("tool_log", []))
        messages = []
        for tc in ai.tool_calls:
            args_key = json.dumps(tc["args"], sort_keys=True, ensure_ascii=False)
            prev = next((e for e in tool_log if e["fn"] == tc["name"] and e["args_key"] == args_key), None)
            if prev is not None:
                note = {"status": "duplicate", "evidence_id": prev["evidence_id"],
                        "note": "与之前的调用完全相同，请直接使用之前的结果，或者换一种排查思路"}
                messages.append(ToolMessage(
                    f"<untrusted_data>\n{json.dumps(note, ensure_ascii=False)}\n</untrusted_data>",
                    tool_call_id=tc["id"]))
                continue
            res = await deps.gateway.invoke(ToolCallReq(id=tc["id"], name=tc["name"], args=tc["args"]), ctx)
            if res.evidence_id:
                evidence_ids.append(res.evidence_id)
            tool_log.append({"fn": tc["name"], "args_key": args_key,
                             "tool": deps.gateway.registry.resolve_id(tc["name"]),
                             "node_id": tc["args"].get("node_id"), "status": res.status,
                             "evidence_id": res.evidence_id})
            messages.append(ToolMessage(res.to_model_content(), tool_call_id=tc["id"]))
        return {"messages": messages, "evidence_ids": evidence_ids, "tool_log": tool_log,
                "step_count": state.get("step_count", 0) + 1}

    return tools
