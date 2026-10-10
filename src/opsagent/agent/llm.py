from typing import Any, Protocol, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from opsagent.config import Settings

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    pass


class LLM(Protocol):
    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage: ...
    async def structured(self, messages: list[BaseMessage], schema: type[T]) -> T: ...


class OpenAICompatLLM:
    def __init__(self, model: Any, structured_method: str = "function_calling") -> None:
        self._model = model
        self._method = structured_method

    @classmethod
    def from_settings(cls, s: Settings) -> "OpenAICompatLLM":
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(base_url=s.llm_base_url, model=s.llm_model, api_key=s.llm_api_key.get_secret_value(),
                           timeout=s.llm_timeout_s, max_retries=2, temperature=0,
                           extra_body=s.llm_extra_body or None)
        return cls(model, s.llm_structured_method)

    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage:
        model = self._model.bind_tools(tools) if tools else self._model
        return await model.ainvoke(messages)

    async def structured(self, messages: list[BaseMessage], schema: type[T]) -> T:
        runnable = self._model.with_structured_output(schema, method=self._method, include_raw=True)
        out = await runnable.ainvoke(messages)
        if out["parsed"] is not None and out["parsing_error"] is None:
            return out["parsed"]
        retry = [*messages, HumanMessage(
            f"上一次的输出不符合格式要求：{out['parsing_error']}。请严格按照 {schema.__name__} 的字段重新输出。")]
        out = await runnable.ainvoke(retry)
        if out["parsed"] is None:
            raise StructuredOutputError(f"{schema.__name__} 两次输出都不合格: {out['parsing_error']}")
        return out["parsed"]
