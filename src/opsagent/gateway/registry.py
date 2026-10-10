from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from pydantic import BaseModel

from .types import AdapterResult

Adapter = Callable[[BaseModel], Awaitable[AdapterResult]]


@dataclass
class ToolSpec:
    id: str
    description: str
    args_model: type[BaseModel]
    adapter: Adapter

    @property
    def fn_name(self) -> str:
        # OpenAI 协议的函数名不允许点号
        return self.id.replace(".", "_")


class ToolRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, ToolSpec] = {}
        self._by_fn: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._by_id[spec.id] = spec
        self._by_fn[spec.fn_name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._by_id.get(name) or self._by_fn.get(name)

    def resolve_id(self, name: str) -> str:
        spec = self.get(name)
        return spec.id if spec else name

    def ids(self) -> set[str]:
        return set(self._by_id)

    def schemas(self, ids: Iterable[str]) -> list[dict]:
        out = []
        for tool_id in ids:
            spec = self._by_id[tool_id]
            out.append({"type": "function", "function": {
                "name": spec.fn_name, "description": spec.description,
                "parameters": spec.args_model.model_json_schema()}})
        return out
