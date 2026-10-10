from datetime import datetime

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from opsagent.agent.graph import build_graph
from opsagent.agent.schemas import Finding, HopStatus, Hypothesis, IntentResult, ReflectVerdict, Report
from opsagent.agent.scripted_llm import tool_call_msg
from tests.helpers import NOW, make_deps

T = {"time_from": "2026-10-09T20:00:00+08:00", "time_to": NOW}
CONFIG = {"configurable": {"thread_id": "s-1"}, "recursion_limit": 60}


def intent(**kw) -> IntentResult:
    base = {"intent": "troubleshoot", "service": "b 服务", "endpoint": "支付接口", "env": "prod",
            "time_from": datetime.fromisoformat(T["time_from"]), "time_to": datetime.fromisoformat(NOW),
            "symptom": "变慢"}
    base.update(kw)
    return IntentResult(**base)


def b_pay_script() -> list:
    return [
        intent(env=None),                                          # 第一次识别：缺环境 → 追问
        intent(),                                                  # 用户回答 prod 后再识别
        tool_call_msg("topology_trace", {"node_id": "svc-b-pay"}),  # ev-1
        AIMessage(content="", tool_calls=[
            {"name": "logs_search", "args": {"node_id": "proxy", "filter": "slow", **T}, "id": "p1"},          # ev-2
            {"name": "metrics_query", "args": {"node_id": "kong", "metric": "upstream_latency_p99", **T},
             "id": "p2"},                                                                                      # ev-3
            {"name": "kong_upstream_health", "args": {"node_id": "kong"}, "id": "p3"}]),                     # ev-4
        AIMessage(content="", tool_calls=[
            {"name": "logs_search", "args": {"node_id": "svc-b", "filter": "error", **T}, "id": "b1"},        # ev-5
            {"name": "changes_list", "args": {"node_id": "svc-b", **T}, "id": "b2"}]),                       # ev-6
        AIMessage("Kong→b 服务这一跳 upstream 延迟升高，b 服务连接池等待超时（ev-5），20:05 发布调小连接池（ev-6）"),
        ReflectVerdict(ok=True),
        Report(summary="b 服务 /api/pay 变慢，第一个异常节点是 Kong → b 服务，疑似连接池过小",
               hops=[HopStatus(node="Kong", status="abnormal", observation="upstream P99 3.1s", evidence_ids=["ev-3"])],
               findings=[Finding(fact="编造", evidence_ids=["ev-999"])],
               hypotheses=[Hypothesis(cause="连接池 maxPoolSize 由 50 调到 20", support=["ev-5", "ev-6"])]),
    ]


async def start(graph, question: str, run_id: str = "run-1"):
    return await graph.ainvoke({"question": question, "run_id": run_id, "now": NOW}, CONFIG)


async def test_troubleshoot_flow_with_clarify(tmp_path):
    deps, llm, rec = await make_deps(tmp_path, b_pay_script())
    graph = build_graph(deps, InMemorySaver())

    await start(graph, "b 服务支付接口昨晚开始变慢")
    snap = await graph.aget_state(CONFIG)
    assert snap.next == ("clarify",)
    question = snap.tasks[0].interrupts[0].value["question"]
    assert "环境" in question

    result = await graph.ainvoke(Command(resume="prod"), CONFIG)
    assert llm.remaining == 0
    report = result["report"]
    assert "连接池" in report["hypotheses"][0]["cause"]
    assert report["dropped_claims"] == 1 and report["findings"] == []
    assert result["partial_reasons"] == [] and result["skill"]["id"] == "http_5xx"
    assert result["evidence_ids"] == ["ev-1", "ev-2", "ev-3", "ev-4", "ev-5", "ev-6"]

    # T3：进入模型的工具结果已经脱敏
    tool_text = "\n".join(m.content for m in result["messages"] if isinstance(m, ToolMessage))
    for leak in ("eyJhbGci", "S3cret", "13812341234", "abcd1234"):
        assert leak not in tool_text
    assert result["history"][-1]["question"] == "b 服务支付接口昨晚开始变慢"


async def test_out_of_scope_calls_no_tools(tmp_path):  # T10
    deps, _, rec = await make_deps(tmp_path, [IntentResult(intent="out_of_scope", reply="一期只读，建议人工重启")])
    result = await start(build_graph(deps, InMemorySaver()), "帮我重启 a 服务")
    assert result["report"]["summary"] == "一期只读，建议人工重启" and rec.calls == []


async def test_budget_exhausted_goes_partial(tmp_path):
    loop = [tool_call_msg("topology_trace", {"node_id": "svc-b-pay"}) for _ in range(16)]
    deps, llm, _ = await make_deps(tmp_path, [intent(), *loop, Report(summary="部分结论")])
    result = await start(build_graph(deps, InMemorySaver()), "b 服务支付接口昨晚开始变慢，prod")
    assert result["step_count"] == 15 and llm.remaining == 0
    assert any("步数上限" in r for r in result["partial_reasons"])


async def test_followup_question_resets_messages_and_keeps_history(tmp_path):
    script = [*b_pay_script(), IntentResult(intent="out_of_scope", reply="好的")]
    deps, llm, _ = await make_deps(tmp_path, script)
    graph = build_graph(deps, InMemorySaver())
    await start(graph, "b 服务支付接口昨晚开始变慢")
    await graph.ainvoke(Command(resume="prod"), CONFIG)

    result = await start(graph, "那 a 服务呢", run_id="run-2")
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])
    assert len(result["history"]) == 2
    intent_prompt = llm.calls[-1]["messages"][0].content
    assert "b 服务支付接口昨晚开始变慢" in intent_prompt  # 上一轮问答作为 history 带入
