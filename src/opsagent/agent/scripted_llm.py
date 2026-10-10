import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel


def tool_call_msg(name: str, args: dict[str, Any], call_id: str | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args,
                                              "id": call_id or f"call_{uuid.uuid4().hex[:8]}"}])


class ScriptedLLM:
    """按预设脚本依次返回结果的假模型：AIMessage 给 chat，BaseModel 实例给 structured，Exception 会被抛出。"""

    def __init__(self, script: list[AIMessage | BaseModel | Exception]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    @property
    def remaining(self) -> int:
        return len(self._script)

    def _next(self) -> Any:
        if not self._script:
            raise AssertionError("ScriptedLLM 脚本已用完")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, messages: list[BaseMessage], tools: list[dict]) -> AIMessage:
        self.calls.append({"kind": "chat", "messages": messages, "tools": tools})
        item = self._next()
        assert isinstance(item, AIMessage), f"chat 期望 AIMessage，脚本给的是 {type(item).__name__}"
        return item

    async def structured(self, messages: list[BaseMessage], schema: type) -> Any:
        self.calls.append({"kind": "structured", "messages": messages, "schema": schema})
        item = self._next()
        assert isinstance(item, schema), f"structured 期望 {schema.__name__}，脚本给的是 {type(item).__name__}"
        return item
