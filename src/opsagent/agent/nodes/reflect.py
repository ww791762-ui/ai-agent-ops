# src/opsagent/agent/nodes/reflect.py
from langchain_core.messages import HumanMessage, SystemMessage

from opsagent.nacos.skill import Skill
from opsagent.topology.model import Topology

from ..deps import Deps
from ..llm import StructuredOutputError
from ..prompting import render
from ..schemas import ReflectVerdict
from ..transcript import render_transcript


def unchecked_hops(state: dict, skill: Skill, topo: Topology) -> list[str]:
    """链路上有可用工具、但还没有被查询过的节点（查询过所属服务也算查过）。"""
    nodes = state.get("nodes", {})
    target = nodes.get("endpoint") or nodes.get("service")
    if not target:
        return []
    queried = {e["node_id"] for e in state.get("tool_log", [])
               if e["tool"] != "topology.trace" and e["status"] != "denied" and e["node_id"]}
    allowed = set(skill.meta.allowed_tools)
    missing: list[str] = []
    for path in topo.trace(target):
        for hop in path.hops:
            if not set(hop.tools) & allowed:
                continue
            parent = topo.get(hop.node_id).parent
            if hop.node_id in queried or (parent and parent in queried) or hop.node_id in missing:
                continue
            missing.append(hop.node_id)
    return missing


def _program_checks(state: dict, skill: Skill, topo: Topology) -> list[str]:
    log = state.get("tool_log", [])
    intent = (state.get("intent") or {}).get("intent")
    issues = []
    if intent == "topology_query":
        if not any(e["tool"] == "topology.trace" and e["status"] == "ok" for e in log):
            issues.append("还没有用 topology_trace 查询链路")
        return issues
    if not any(e["status"] in ("ok", "truncated") for e in log):
        issues.append("还没有获取到任何有效证据")
    missing = unchecked_hops(state, skill, topo)
    if missing:
        issues.append("链路上以下节点还没有检查：" + "、".join(missing))
    return issues


def make_reflect(deps: Deps):
    async def reflect(state: dict) -> dict:
        skill = deps.store.skill_by_md5(state["skill"]["md5"])
        issues = _program_checks(state, skill, deps.topo)
        if not issues:
            prompt = render(deps.store.prompt("ops.reflect.inrun").template,
                            required_evidence="、".join(skill.meta.required_evidence) or "无")
            try:
                verdict = await deps.llm.structured(
                    [SystemMessage(prompt), HumanMessage(render_transcript(state))], ReflectVerdict)
            except StructuredOutputError:
                return {"reflect_retry": False,
                        "partial_reasons": [*state.get("partial_reasons", []),
                                            "反思检查失败（模型输出不合格），未完成自查"]}
            issues = [] if verdict.ok else (verdict.issues or ["审核未通过"])
        if not issues:
            return {"reflect_retry": False}
        rounds = state.get("reflect_rounds", 0)
        if rounds >= 1:  # 只补查一轮
            return {"reflect_retry": False,
                    "partial_reasons": [*state.get("partial_reasons", []), "反思检查未通过：" + "；".join(issues)]}
        return {"reflect_retry": True, "reflect_rounds": rounds + 1,
                "messages": [HumanMessage("【系统自查】给出结论前发现以下问题，请补充查询后再给出结论：\n- "
                                          + "\n- ".join(issues))]}

    return reflect
