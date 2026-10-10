from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from opsagent.agent.llm import StructuredOutputError
from opsagent.agent.nodes.agent_step import make_agent_step
from opsagent.agent.nodes.finalize import make_finalize
from opsagent.agent.nodes.reflect import make_reflect
from opsagent.agent.nodes.tools import make_tools
from opsagent.agent.schemas import Finding, HopStatus, Hypothesis, ReflectVerdict, Report
from opsagent.agent.scripted_llm import tool_call_msg
from tests.helpers import NOW, make_deps, skill_ref

T = {"time_from": "2026-10-09T20:00:00+08:00", "time_to": NOW}


def ts_state(store, **over) -> dict:
    s = {"question": "b 服务支付接口变慢", "run_id": "run-1", "now": NOW, "history": [],
         "intent": {"intent": "troubleshoot", "env": "prod", **T},
         "nodes": {"service": "svc-b", "endpoint": "svc-b-pay"}, "assumptions": [],
         "skill": skill_ref(store, "http_5xx"), "messages": [HumanMessage("b 服务支付接口变慢")],
         "step_count": 0, "reflect_rounds": 0, "evidence_ids": [], "tool_log": [], "partial_reasons": []}
    s.update(over)
    return s


def log(tool, node, status="ok", ev="ev-1"):
    return {"fn": tool.replace(".", "_"), "args_key": f"{tool}-{node}", "tool": tool, "node_id": node,
            "status": status, "evidence_id": ev}


FULL_LOG = [log("topology.trace", "svc-b-pay"), log("logs.search", "proxy", ev="ev-2"),
            log("metrics.query", "kong", ev="ev-3"), log("logs.search", "svc-b", ev="ev-4")]


async def test_agent_step_binds_only_skill_tools(tmp_path):
    deps, llm, _ = await make_deps(tmp_path, [AIMessage("结论")])
    out = await make_agent_step(deps)(ts_state(deps.store))
    assert out["messages"][0].content == "结论"
    names = sorted(t["function"]["name"] for t in llm.calls[0]["tools"])
    assert names == ["changes_list", "kong_upstream_health", "logs_search", "metrics_query", "topology_trace"]
    system = llm.calls[0]["messages"][0].content
    assert "HTTP 接口错误" in system and "svc-b-pay" in system and NOW in system


async def test_tools_node_calls_gateway_and_counts_step(tmp_path):  # T5
    deps, _, rec = await make_deps(tmp_path, [])
    ai = AIMessage(content="", tool_calls=[
        {"name": "topology_trace", "args": {"node_id": "svc-b-pay"}, "id": "c1"},
        {"name": "shell_exec", "args": {"cmd": "reboot"}, "id": "c2"}])
    out = await make_tools(deps)(ts_state(deps.store, messages=[HumanMessage("q"), ai]))
    msgs = out["messages"]
    assert all(isinstance(m, ToolMessage) for m in msgs) and [m.tool_call_id for m in msgs] == ["c1", "c2"]
    assert "ev-1" in msgs[0].content and '"denied"' in msgs[1].content
    assert out["evidence_ids"] == ["ev-1"] and out["step_count"] == 1
    assert [e["tool"] for e in out["tool_log"]] == ["topology.trace", "shell_exec"]
    assert len(rec.calls) == 2


async def test_tools_node_short_circuits_duplicate_call(tmp_path):
    deps, _, rec = await make_deps(tmp_path, [])
    tools = make_tools(deps)
    first = await tools(ts_state(deps.store, messages=[tool_call_msg("topology_trace", {"node_id": "svc-b"}, "c1")]))
    second = await tools(ts_state(deps.store, tool_log=first["tool_log"],
                                  messages=[tool_call_msg("topology_trace", {"node_id": "svc-b"}, "c2")]))
    assert "duplicate" in second["messages"][0].content and len(rec.calls) == 1


async def test_reflect_without_evidence_asks_agent_to_continue(tmp_path):
    deps, llm, _ = await make_deps(tmp_path, [])  # 程序检查不通过时不调用模型
    out = await make_reflect(deps)(ts_state(deps.store))
    assert out["reflect_retry"] is True and out["reflect_rounds"] == 1
    assert "系统自查" in out["messages"][0].content and llm.calls == []


async def test_reflect_second_failure_goes_partial(tmp_path):  # T17
    deps, _, _ = await make_deps(tmp_path, [])
    out = await make_reflect(deps)(ts_state(deps.store, reflect_rounds=1))
    assert out["reflect_retry"] is False
    assert any("反思检查未通过" in r for r in out["partial_reasons"])


async def test_reflect_reports_unchecked_hops(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [])
    out = await make_reflect(deps)(ts_state(deps.store, tool_log=FULL_LOG[:2]))
    assert out["reflect_retry"] is True and "kong" in out["messages"][0].content


async def test_reflect_passes_with_llm_ok(tmp_path):
    deps, llm, _ = await make_deps(tmp_path, [ReflectVerdict(ok=True)])
    out = await make_reflect(deps)(ts_state(deps.store, tool_log=FULL_LOG))
    assert out["reflect_retry"] is False and out.get("partial_reasons", []) == []
    assert "链路逐跳状态" in llm.calls[0]["messages"][0].content


async def test_reflect_llm_issue_triggers_retry(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [ReflectVerdict(ok=False, issues=["缺少变更记录"])])
    out = await make_reflect(deps)(ts_state(deps.store, tool_log=FULL_LOG))
    assert out["reflect_retry"] is True and "缺少变更记录" in out["messages"][0].content


async def test_finalize_drops_unknown_evidence_and_updates_history(tmp_path):  # T8
    report = Report(summary="连接池耗尽", hops=[HopStatus(node="kong", status="abnormal", evidence_ids=["ev-1"])],
                    findings=[Finding(fact="编造的事实", evidence_ids=["ev-999"])],
                    hypotheses=[Hypothesis(cause="连接池", support=["ev-1"])])
    deps, _, _ = await make_deps(tmp_path, [report])
    out = await make_finalize(deps)(ts_state(deps.store, evidence_ids=["ev-1"], assumptions=["默认 prod"]))
    r = out["report"]
    assert r["findings"] == [] and r["dropped_claims"] == 1 and len(r["hops"]) == 1
    assert r["assumptions"] == ["默认 prod"] and out["partial_reasons"] == []
    assert out["history"][-1] == {"question": "b 服务支付接口变慢", "answer": "连接池耗尽"}


async def test_finalize_out_of_scope_uses_reply_without_llm(tmp_path):  # T10
    deps, llm, _ = await make_deps(tmp_path, [])
    out = await make_finalize(deps)(ts_state(deps.store, intent={"intent": "out_of_scope", "reply": "一期只读"}))
    assert out["report"]["summary"] == "一期只读" and llm.calls == []


async def test_finalize_unresolved_needs_human(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [])
    out = await make_finalize(deps)(ts_state(deps.store, unresolved=["「支付服务」对应多个节点"]))
    assert out["report"]["needs_human"] is True and "支付服务" in out["report"]["summary"]


async def test_finalize_marks_budget_exhausted(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [Report(summary="部分结论")])
    msgs = [HumanMessage("q"), tool_call_msg("topology_trace", {"node_id": "svc-b"})]
    out = await make_finalize(deps)(ts_state(deps.store, messages=msgs))
    assert any("步数上限" in r for r in out["partial_reasons"])


async def test_finalize_structured_failure_falls_back_to_text(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [StructuredOutputError("bad")])
    msgs = [HumanMessage("q"), AIMessage("纯文本结论")]
    out = await make_finalize(deps)(ts_state(deps.store, messages=msgs))
    assert out["report"]["summary"] == "纯文本结论"
    assert any("纯文本" in r for r in out["partial_reasons"])


async def test_finalize_redacts_output(tmp_path):  # T3（输出侧）
    deps, _, _ = await make_deps(tmp_path, [Report(summary="日志里有 token=abc123 和 13812341234")])
    out = await make_finalize(deps)(ts_state(deps.store))
    assert "abc123" not in out["report"]["summary"] and "138****1234" in out["report"]["summary"]


async def test_reflect_structured_failure_degrades_without_retry(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [StructuredOutputError("bad")])
    out = await make_reflect(deps)(ts_state(deps.store, tool_log=FULL_LOG))
    assert out["reflect_retry"] is False
    assert any("反思检查失败" in r for r in out["partial_reasons"])
