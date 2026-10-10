from datetime import datetime, timedelta

from langchain_core.messages import SystemMessage

from opsagent.topology.model import Topology

from ..deps import Deps
from ..prompting import format_history, render
from ..schemas import IntentResult

REQUIRED_SLOTS = {"troubleshoot": ("env", "time"), "topology_query": ()}
SLOT_QUESTIONS = {"env": "是哪个环境？（prod / test）", "time": "问题大概从什么时间开始？（例如：昨晚 20:00）"}


def link_entities(topo: Topology, r: IntentResult) -> tuple[dict[str, str], list[str]]:
    """把用户说的名称映射为拓扑节点 ID。返回 (已解析的节点, 问题列表)。"""
    nodes: dict[str, str] = {}
    problems: list[str] = []
    if r.endpoint:
        found = topo.find(r.endpoint)
        if len(found) == 1:
            nodes["endpoint"] = found[0].id
        elif not found:
            problems.append(f"拓扑中没有找到「{r.endpoint}」，请确认名称")
        else:
            problems.append(f"「{r.endpoint}」对应多个节点：{'、'.join(f'{n.name}（{n.id}）' for n in found)}，请问是哪一个？")
    if r.service:
        found = topo.find(r.service)
        parent = topo.get(nodes["endpoint"]).parent if "endpoint" in nodes else None
        if len(found) > 1 and parent in {n.id for n in found}:
            found = [n for n in found if n.id == parent]  # 用接口的所属服务消除歧义
        if len(found) == 1:
            nodes["service"] = found[0].id
        elif not found:
            problems.append(f"拓扑中没有找到「{r.service}」，请确认名称")
        else:
            problems.append(f"「{r.service}」对应多个节点：{'、'.join(f'{n.name}（{n.id}）' for n in found)}，请问是哪一个？")
    if not nodes and not problems:
        problems.append("请问要排查或查询的是哪个服务或接口？")
    return nodes, problems


def _missing_slots(r: IntentResult) -> list[str]:
    slots = REQUIRED_SLOTS[r.intent]
    missing = []
    if "env" in slots and not r.env:
        missing.append("env")
    if "time" in slots and not (r.time_from and r.time_to):
        missing.append("time")
    return missing


def make_intent(deps: Deps):
    async def intent(state: dict) -> dict:
        prompt = render(deps.store.prompt("ops.intent").template, now=state["now"],
                        history=format_history(state.get("history", [])))
        r = await deps.llm.structured([SystemMessage(prompt), *state["messages"]], IntentResult)
        if r.intent == "out_of_scope":
            return {"intent": r.model_dump(mode="json"), "clarify_question": None, "unresolved": []}

        nodes, problems = link_entities(deps.topo, r)
        missing = _missing_slots(r)
        if state.get("clarify_count", 0) == 0 and (problems or missing or r.confidence == "low"):
            lines = [*problems, *(SLOT_QUESTIONS[m] for m in missing)]
            if r.confidence == "low" and not lines:
                lines.append(f"我理解你想了解：{r.symptom or state['question']}，对吗？")
            return {"intent": r.model_dump(mode="json"), "clarify_question": "\n".join(lines), "unresolved": []}

        # 已经追问过一次：缺失的字段使用默认值，仍无法确定的实体交给 finalize 处理
        assumptions = []
        now = datetime.fromisoformat(state["now"])
        if "time" in missing:
            r.time_from, r.time_to = now - timedelta(hours=1), now
            assumptions.append("未给出时间范围，默认使用最近 1 小时")
        if "env" in missing:
            r.env = "prod"
            assumptions.append("未给出环境，默认使用 prod")
        return {"intent": r.model_dump(mode="json"), "nodes": nodes, "assumptions": assumptions,
                "clarify_question": None, "unresolved": problems}

    return intent
