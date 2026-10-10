import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from opsagent.redaction.redactor import Redactor
from opsagent.topology.model import Topology

from .registry import ToolRegistry, ToolSpec
from .types import AdapterResult, EvidenceRecorder, RunContext, ToolCallReq, ToolResult, TransientError

log = logging.getLogger(__name__)

_FIXED_ERRORS = {"敏感数据过滤失败，结果已丢弃"}  # 网关自带的固定文案，不含外部内容


class Gateway:
    """所有工具调用的唯一入口：白名单 → 参数校验 → 节点校验 → 执行（含重试）→ 脱敏 → 记录。"""

    def __init__(self, registry: ToolRegistry, topo: Topology, recorder: EvidenceRecorder,
                 redactor_provider: Callable[[], Redactor], timeout_s: float = 30.0, retries: int = 2,
                 backoff_s: float = 0.5) -> None:
        self.registry = registry
        self._topo = topo
        self._recorder = recorder
        self._redactor_provider = redactor_provider
        self._timeout_s = timeout_s
        self._retries = retries
        self._backoff_s = backoff_s

    async def invoke(self, call: ToolCallReq, ctx: RunContext) -> ToolResult:
        started = time.monotonic()
        spec = self.registry.get(call.name)
        if spec is None:
            return await self._finish(ctx, call.name, call.args, started,
                                      ToolResult(status="denied", error=f"未注册的工具: {call.name}"))
        if spec.id not in ctx.allowed_tools:
            return await self._finish(ctx, spec.id, call.args, started,
                                      ToolResult(status="denied", error=f"当前 Skill 不允许使用工具 {spec.id}"))
        try:
            args = spec.args_model.model_validate(call.args)
        except ValidationError as e:
            return await self._finish(ctx, spec.id, call.args, started, ToolResult(
                status="denied", error=f"参数不合法: {e.errors(include_url=False, include_context=False)}"))
        node_id = getattr(args, "node_id", None)
        if node_id is not None and self._topo.get(node_id) is None:
            return await self._finish(ctx, spec.id, call.args, started,
                                      ToolResult(status="denied", error=f"节点未在拓扑中登记: {node_id}"))
        try:
            res = await self._call_with_retry(spec, args)
        except Exception as e:
            try:  # 先脱敏再截断，避免截断把敏感串切坏导致规则漏匹配；原始异常不进日志
                detail = self._redactor_provider().with_salt(ctx.run_id).redact_text(str(e))[:200]
            except Exception:
                detail = "错误信息已隐藏"
            log.warning("工具 %s 执行失败: %s: %s", spec.id, type(e).__name__, detail)
            return await self._finish(ctx, spec.id, call.args, started,
                                      ToolResult(status="backend_error", error=f"后端调用失败: {detail}"))
        try:
            stats: Counter = Counter()
            plain = json.loads(json.dumps(res.data, ensure_ascii=False, default=str))
            data = self._redactor_provider().with_salt(ctx.run_id).redact_obj(plain, stats)
        except Exception:
            log.exception("工具 %s 的结果脱敏失败，已丢弃", spec.id)
            return await self._finish(ctx, spec.id, call.args, started,
                                      ToolResult(status="backend_error", error="敏感数据过滤失败，结果已丢弃"))
        return await self._finish(ctx, spec.id, call.args, started,
                                  ToolResult(status=res.status, data=data, redaction_stats=dict(stats)))

    async def _call_with_retry(self, spec: ToolSpec, args: Any) -> AdapterResult:
        for attempt in range(self._retries + 1):
            try:
                return await asyncio.wait_for(spec.adapter(args), self._timeout_s)
            except (TransientError, TimeoutError):
                if attempt == self._retries:
                    raise
                await asyncio.sleep(self._backoff_s * 2 ** attempt)
        raise AssertionError("unreachable")

    async def _finish(self, ctx: RunContext, tool_id: str, raw_args: dict, started: float,
                      result: ToolResult) -> ToolResult:
        try:
            redactor = self._redactor_provider().with_salt(ctx.run_id)
            args = redactor.redact_obj(raw_args)
            if result.error is not None:
                result = result.model_copy(update={"error": redactor.redact_text(result.error)})
        except Exception:
            log.exception("工具 %s 的参数/错误信息脱敏失败", tool_id)
            args = {}
            if result.error is not None and result.error not in _FIXED_ERRORS:
                result = result.model_copy(update={"error": "错误信息已隐藏"})
        try:
            evidence_id = await self._recorder.record(
                run_id=ctx.run_id, tool=tool_id, args=args, status=result.status, data=result.data,
                redaction_stats=result.redaction_stats,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=result.error, make_evidence=result.status in ("ok", "truncated"))
        except Exception:
            log.exception("工具 %s 的调用记录写入失败，结果已丢弃", tool_id)
            return ToolResult(status="backend_error", error="调用记录写入失败，结果已丢弃")
        return result.model_copy(update={"evidence_id": evidence_id})
