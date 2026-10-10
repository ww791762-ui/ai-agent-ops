from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from ..registry import Adapter
from ..types import AdapterResult, TransientError


class MockResponse(BaseModel):
    tool: str
    match: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "empty", "truncated", "error", "transient"] = "ok"
    data: Any = None


class MockScenario(BaseModel):
    name: str
    description: str = ""
    responses: list[MockResponse]

    @classmethod
    def from_yaml_file(cls, path: Path) -> "MockScenario":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def _matches(match: dict[str, Any], args: dict[str, Any]) -> bool:
    for key, expected in match.items():
        actual = args.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def mock_adapter(scenario: MockScenario, tool_id: str) -> Adapter:
    async def run(args: BaseModel) -> AdapterResult:
        values = args.model_dump(mode="json")
        for r in scenario.responses:
            if r.tool == tool_id and _matches(r.match, values):
                if r.status == "transient":
                    raise TransientError(f"mock {tool_id} 暂时不可用")
                if r.status == "error":
                    raise RuntimeError(f"mock {tool_id} 后端错误")
                return AdapterResult(status=r.status, data=r.data)
        return AdapterResult(status="empty")

    return run
