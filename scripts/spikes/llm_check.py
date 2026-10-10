"""一次性脚本：验证 glm-5.2 的 tool calling 和结构化输出。不进入正式代码。"""
import asyncio

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from opsagent.config import Settings


class Weather(BaseModel):
    city: str
    unit: str


TOOL = {
    "type": "function",
    "function": {
        "name": "metrics_query",
        "description": "查询某个节点的指标",
        "parameters": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}, "metric": {"type": "string"}},
            "required": ["node_id", "metric"],
        },
    },
}


async def main() -> None:
    s = Settings()
    m = ChatOpenAI(base_url=s.llm_base_url, model=s.llm_model,
                   api_key=s.llm_api_key.get_secret_value(), timeout=60, temperature=0)
    try:
        r = await m.bind_tools([TOOL]).ainvoke("查询节点 svc-b 的 error_rate 指标")
        print("[tool calling] tool_calls =", r.tool_calls)
    except Exception as e:
        print("[tool calling] FAILED:", repr(e))
    for method in ("function_calling", "json_schema", "json_mode"):
        try:
            out = await m.with_structured_output(Weather, method=method).ainvoke(
                "用户说：北京，摄氏度。请提取城市和温度单位，以 JSON 输出，字段 city、unit。")
            print(f"[structured:{method}] =", out)
        except Exception as e:
            print(f"[structured:{method}] FAILED:", repr(e))


asyncio.run(main())
