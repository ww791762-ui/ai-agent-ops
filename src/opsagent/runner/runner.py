import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.types import Command

from opsagent.agent.schemas import LOCAL_TZ
from opsagent.ids import new_id
from opsagent.nacos.store import ConfigStore
from opsagent.storage.repo import RunRepo


def local_now_iso(dt: datetime) -> str:
    """Prompt 中的 {{now}} 约定为 Asia/Shanghai 时间，与宿主机时区无关。"""
    return dt.astimezone(LOCAL_TZ).isoformat()


log = logging.getLogger(__name__)


class SessionBusy(Exception):
    pass


class Runner:
    def __init__(self, graph: Any, runs: RunRepo, store: ConfigStore,
                 clarify_timeout: timedelta = timedelta(minutes=30),
                 clock: Callable[[], datetime] | None = None,
                 run_timeout: timedelta = timedelta(minutes=10)) -> None:
        self._graph = graph
        self._runs = runs
        self._store = store
        self._clarify_timeout = clarify_timeout
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_timeout = run_timeout
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        self._live: dict[str, asyncio.Task] = {}  # 本进程正在执行的 Run：run_id → Task

    async def submit(self, session_id: str | None, message: str) -> tuple[str, str]:
        session_id = session_id or new_id("s")
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._submit_locked(session_id, message)

    async def _submit_locked(self, session_id: str, message: str) -> tuple[str, str]:
        active = await self._runs.active_run(session_id)
        if active:
            # 本进程仍在执行的 Run 永远不算过期；只有无人认领（如上一个进程遗留）的 running 才按超时回收
            live = self._live.get(active.id)
            if (live is None or live.done()) and self._clock() - active.updated_at > self._run_timeout:
                await self._runs.finish(active.id, status="failed", error="运行超时，状态已过期")
            else:
                raise SessionBusy(session_id)
        waiting = await self._runs.waiting_run(session_id)
        if waiting and self._clock() - waiting.updated_at > self._clarify_timeout:
            await self._runs.finish(waiting.id, status="cancelled", error="追问超过时限未回复")
            waiting = None
        if waiting:
            # 先脱敏再进图：checkpoint 里只保存脱敏后的回答
            answer = self._store.redactor().with_salt(waiting.id).redact_text(message)
            await self._runs.mark_running(waiting.id)
            self._spawn(waiting.id, session_id, Command(resume=answer))
            return session_id, waiting.id

        run_id = new_id("run")
        question = self._store.redactor().with_salt(run_id).redact_text(message)
        await self._runs.create(run_id=run_id, session_id=session_id, question=question,
                                prompt_versions=self._store.versions())
        await self._runs.mark_running(run_id)
        self._spawn(run_id, session_id, {"question": question, "run_id": run_id,
                                         "now": local_now_iso(self._clock())})
        return session_id, run_id

    def _spawn(self, run_id: str, session_id: str, graph_input: Any) -> None:
        task = asyncio.create_task(self._execute(run_id, session_id, graph_input))
        self._tasks.add(task)
        self._live[run_id] = task
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda t: self._live.pop(run_id, None) if self._live.get(run_id) is t else None)

    async def _execute(self, run_id: str, session_id: str, graph_input: Any) -> None:
        config = {"configurable": {"thread_id": session_id}, "recursion_limit": 60}
        try:
            deadline = asyncio.timeout(self._run_timeout.total_seconds())
            try:
                async with deadline:
                    result = await self._graph.ainvoke(graph_input, config)
            except TimeoutError:
                if not deadline.expired():
                    raise  # 图内部抛出的 TimeoutError，按普通异常处理
                log.warning("Run %s 运行超时", run_id)
                await self._runs.finish(run_id, status="failed", error="运行超时")
                return
            snap = await self._graph.aget_state(config)
            pending = [i for t in snap.tasks for i in t.interrupts]
            if pending:
                await self._runs.set_waiting(run_id, pending[0].value["question"])
                return
            partial = result.get("partial_reasons", [])
            await self._runs.finish(run_id, status="partial" if partial else "completed",
                                    report=result.get("report"), intent=result.get("intent"),
                                    skill=result.get("skill"), step_count=result.get("step_count", 0),
                                    partial_reasons=partial)
        except Exception as e:
            log.exception("Run %s 执行失败", run_id)
            try:
                await self._runs.finish(run_id, status="failed", error=self._safe_error(run_id, e))
            except Exception:
                log.exception("Run %s 标记失败状态时出错", run_id)

    def _safe_error(self, run_id: str, e: Exception) -> str:
        """存库的错误信息先按 Run 盐值脱敏再截断；脱敏失败时只保留异常类型。"""
        try:
            return self._store.redactor().with_salt(run_id).redact_text(f"{type(e).__name__}: {e}")[:500]
        except Exception:
            return f"{type(e).__name__}: 错误信息已隐藏"

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
