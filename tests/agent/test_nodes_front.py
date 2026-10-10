from datetime import datetime

from langchain_core.messages import HumanMessage, RemoveMessage

from opsagent.agent.nodes.intent import make_intent
from opsagent.agent.nodes.redact_input import make_redact_input
from opsagent.agent.nodes.route_skill import make_route_skill
from opsagent.agent.schemas import IntentResult
from tests.helpers import NOW, make_deps

T_FROM = datetime.fromisoformat("2026-10-09T20:00:00+08:00")
T_TO = datetime.fromisoformat(NOW)


def state(**over) -> dict:
    s = {"question": "b 服务支付接口昨晚开始变慢", "run_id": "run-1", "now": NOW,
         "messages": [HumanMessage("b 服务支付接口昨晚开始变慢")], "history": [], "clarify_count": 0}
    s.update(over)
    return s


def intent(**kw) -> IntentResult:
    base = {"intent": "troubleshoot", "service": "b 服务", "endpoint": "支付接口", "env": "prod",
            "time_from": T_FROM, "time_to": T_TO, "symptom": "变慢"}
    base.update(kw)
    return IntentResult(**base)


async def test_redact_input_resets_run_fields_and_redacts(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [])
    out = await make_redact_input(deps)({"question": "token=abc123 b 服务慢", "run_id": "run-1", "step_count": 9})
    assert "abc123" not in out["question"]
    assert out["step_count"] == 0 and out["evidence_ids"] == [] and out["reflect_rounds"] == 0
    assert isinstance(out["messages"][0], RemoveMessage)
    assert out["messages"][1].content == out["question"]


async def test_intent_resolved_without_clarify(tmp_path):
    deps, llm, _ = await make_deps(tmp_path, [intent()])
    out = await make_intent(deps)(state())
    assert out["clarify_question"] is None and out["unresolved"] == []
    assert out["nodes"] == {"service": "svc-b", "endpoint": "svc-b-pay"}
    assert out["assumptions"] == []
    assert NOW in llm.calls[0]["messages"][0].content  # {{now}} 已渲染


async def test_ambiguous_service_asks_with_candidates(tmp_path):  # T9
    deps, _, _ = await make_deps(tmp_path, [intent(service="支付服务", endpoint=None)])
    out = await make_intent(deps)(state())
    q = out["clarify_question"]
    assert "svc-b" in q and "svc-paycb" in q


async def test_ambiguous_service_resolved_by_endpoint_parent(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [intent(service="支付服务", endpoint="支付接口")])
    out = await make_intent(deps)(state())
    assert out["clarify_question"] is None
    assert out["nodes"] == {"service": "svc-b", "endpoint": "svc-b-pay"}


async def test_missing_env_asks(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [intent(env=None)])
    out = await make_intent(deps)(state())
    assert "环境" in out["clarify_question"]


async def test_low_confidence_asks(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [intent(confidence="low")])
    out = await make_intent(deps)(state())
    assert "对吗" in out["clarify_question"]


async def test_after_clarify_missing_slots_use_defaults(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [intent(env=None, time_from=None, time_to=None)])
    out = await make_intent(deps)(state(clarify_count=1))
    assert out["clarify_question"] is None
    assert out["intent"]["env"] == "prod"
    assert out["intent"]["time_to"].startswith("2026-10-10T10:00")
    assert len(out["assumptions"]) == 2


async def test_after_clarify_still_ambiguous_is_unresolved(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [intent(service="支付服务", endpoint=None)])
    out = await make_intent(deps)(state(clarify_count=1))
    assert out["clarify_question"] is None and out["unresolved"]


async def test_out_of_scope_no_clarify(tmp_path):  # T10
    deps, _, _ = await make_deps(tmp_path, [IntentResult(intent="out_of_scope", reply="一期只读，建议人工执行")])
    out = await make_intent(deps)(state(question="帮我重启 a 服务"))
    assert out["intent"]["intent"] == "out_of_scope" and out["clarify_question"] is None


async def test_route_skill_by_keyword_and_fallback(tmp_path):
    deps, _, _ = await make_deps(tmp_path, [])
    route = make_route_skill(deps)
    hit = await route(state(intent={"intent": "troubleshoot", "symptom": "变慢"}))
    assert hit["skill"]["id"] == "http_5xx" and len(hit["skill"]["md5"]) == 32
    generic = await route(state(question="b 服务有点奇怪", intent={"intent": "troubleshoot", "symptom": None}))
    assert generic["skill"]["id"] == "generic_troubleshoot"
    topo = await route(state(question="C 服务调 OCR 走哪条链路", intent={"intent": "topology_query"}))
    assert topo["skill"]["id"] == "topology_qa"
