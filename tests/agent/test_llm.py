import pytest
from langchain_core.messages import AIMessage, HumanMessage

from opsagent.agent.llm import OpenAICompatLLM, StructuredOutputError
from opsagent.agent.schemas import IntentResult, ReflectVerdict
from opsagent.agent.scripted_llm import ScriptedLLM, tool_call_msg


async def test_scripted_llm_returns_in_order():
    llm = ScriptedLLM([IntentResult(intent="troubleshoot"), tool_call_msg("logs_search", {"node_id": "svc-b"})])
    assert (await llm.structured([], IntentResult)).intent == "troubleshoot"
    msg = await llm.chat([], tools=[])
    assert msg.tool_calls[0]["name"] == "logs_search" and msg.tool_calls[0]["id"]
    assert llm.remaining == 0 and [c["kind"] for c in llm.calls] == ["structured", "chat"]
    with pytest.raises(AssertionError, match="脚本已用完"):
        await llm.chat([], tools=[])


async def test_scripted_llm_type_mismatch():
    with pytest.raises(AssertionError):
        await ScriptedLLM([AIMessage("x")]).structured([], IntentResult)


class FakeRunnable:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.inputs = []

    async def ainvoke(self, messages):
        self.inputs.append(messages)
        return self.outputs.pop(0)


class FakeChatModel:
    def __init__(self, runnable):
        self.runnable = runnable
        self.kwargs = None

    def with_structured_output(self, schema, **kwargs):
        self.kwargs = kwargs
        return self.runnable


async def test_structured_repairs_once():
    good = ReflectVerdict(ok=True)
    runnable = FakeRunnable([
        {"raw": None, "parsed": None, "parsing_error": ValueError("bad json")},
        {"raw": None, "parsed": good, "parsing_error": None},
    ])
    model = FakeChatModel(runnable)
    out = await OpenAICompatLLM(model).structured([HumanMessage("q")], ReflectVerdict)
    assert out is good
    assert model.kwargs == {"method": "function_calling", "include_raw": True}
    assert "bad json" in runnable.inputs[1][-1].content


async def test_structured_raises_after_second_failure():
    bad = {"raw": None, "parsed": None, "parsing_error": ValueError("bad")}
    llm = OpenAICompatLLM(FakeChatModel(FakeRunnable([bad, bad])))
    with pytest.raises(StructuredOutputError):
        await llm.structured([HumanMessage("q")], ReflectVerdict)


def test_from_settings_disables_thinking_and_uses_long_timeout():
    from opsagent.config import Settings

    s = Settings(_env_file=None, llm_api_key="k")
    model = OpenAICompatLLM.from_settings(s)._model
    assert model.request_timeout == 180
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_from_settings_thinking_switch_and_extra_body_merge():
    from opsagent.config import Settings

    s = Settings(_env_file=None, llm_api_key="k", llm_thinking=True, llm_extra_body={"top_k": 5})
    assert OpenAICompatLLM.from_settings(s)._model.extra_body == {"thinking": {"type": "enabled"}, "top_k": 5}
    s = Settings(_env_file=None, llm_api_key="k", llm_extra_body={"thinking": {"type": "auto"}})
    assert OpenAICompatLLM.from_settings(s)._model.extra_body == {"thinking": {"type": "auto"}}
