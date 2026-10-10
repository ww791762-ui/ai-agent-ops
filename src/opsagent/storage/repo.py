from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from opsagent.ids import new_id
from opsagent.topology.model import Edge, Node, PathDef, Topology

from .models import (AuditRow, EvidenceRow, ReportRow, RunRow, SessionRow, ToolCallRow, TopoEdgeRow,
                     TopoNodeRow, TopoPathRow)


class RunRepo:
    def __init__(self, sm: async_sessionmaker) -> None:
        self._sm = sm

    async def create(self, *, run_id: str, session_id: str, question: str, prompt_versions: dict) -> None:
        async with self._sm.begin() as s:
            if await s.get(SessionRow, session_id) is None:
                s.add(SessionRow(id=session_id))
                await s.flush()
            s.add(RunRow(id=run_id, session_id=session_id, question=question, status="queued",
                         prompt_versions=prompt_versions))

    async def get(self, run_id: str) -> RunRow | None:
        async with self._sm() as s:
            return await s.get(RunRow, run_id)

    async def _latest(self, session_id: str, statuses: tuple[str, ...]) -> RunRow | None:
        async with self._sm() as s:
            stmt = (select(RunRow).where(RunRow.session_id == session_id, RunRow.status.in_(statuses))
                    .order_by(RunRow.created_at.desc()).limit(1))
            return (await s.scalars(stmt)).first()

    async def active_run(self, session_id: str) -> RunRow | None:
        return await self._latest(session_id, ("queued", "running"))

    async def waiting_run(self, session_id: str) -> RunRow | None:
        return await self._latest(session_id, ("waiting_user",))

    async def _update(self, run_id: str, **values: Any) -> None:
        async with self._sm.begin() as s:
            await s.execute(update(RunRow).where(RunRow.id == run_id)
                            .values(**values, updated_at=datetime.now(UTC)))

    async def mark_running(self, run_id: str) -> None:
        await self._update(run_id, status="running", pending_question=None)

    async def set_waiting(self, run_id: str, question: str) -> None:
        await self._update(run_id, status="waiting_user", pending_question=question)

    async def finish(self, run_id: str, *, status: str, report: dict | None = None, intent: dict | None = None,
                     skill: dict | None = None, step_count: int = 0, partial_reasons: Iterable[str] = (),
                     error: str | None = None) -> None:
        async with self._sm.begin() as s:
            run = await s.get(RunRow, run_id)
            run.status = status
            run.step_count = step_count
            run.partial_reasons = list(partial_reasons)
            run.error = error
            run.pending_question = None
            run.updated_at = datetime.now(UTC)
            if intent is not None:
                run.intent = intent
            if skill:
                run.skill_id, run.skill_version, run.skill_md5 = skill["id"], skill["version"], skill["md5"]
            if report is not None:
                s.add(ReportRow(run_id=run_id, content=report))

    async def report(self, run_id: str) -> dict | None:
        async with self._sm() as s:
            row = await s.get(ReportRow, run_id)
            return row.content if row else None


class DbRecorder:
    """网关的 EvidenceRecorder 实现：写 tool_calls、evidences，拒绝的调用另写 audit_log。"""

    def __init__(self, sm: async_sessionmaker) -> None:
        self._sm = sm

    async def record(self, *, run_id: str, tool: str, args: dict, status: str, data: Any,
                     redaction_stats: dict, duration_ms: int, error: str | None,
                     make_evidence: bool) -> str | None:
        call_id = new_id("tc")
        evidence_id = new_id("ev") if make_evidence else None
        async with self._sm.begin() as s:
            s.add(ToolCallRow(id=call_id, run_id=run_id, tool=tool, args=args, status=status,
                              duration_ms=duration_ms, error=error))
            await s.flush()
            if evidence_id:
                s.add(EvidenceRow(id=evidence_id, run_id=run_id, tool_call_id=call_id, tool=tool,
                                  content=data, redaction_stats=redaction_stats))
            if status == "denied":
                s.add(AuditRow(actor=f"run:{run_id}", action=f"tool:{tool}", target=str(args.get("node_id", "")),
                               result="denied", detail={"error": error}))
        return evidence_id

    async def get_evidence(self, evidence_id: str) -> dict | None:
        async with self._sm() as s:
            row = await s.get(EvidenceRow, evidence_id)
            if row is None:
                return None
            return {"id": row.id, "run_id": row.run_id, "tool": row.tool, "content": row.content,
                    "redaction_stats": row.redaction_stats, "created_at": row.created_at.isoformat()}


class TopologyRepo:
    def __init__(self, sm: async_sessionmaker) -> None:
        self._sm = sm

    async def replace_all(self, topo: Topology, updated_by: str) -> None:
        async with self._sm.begin() as s:
            for table in (TopoPathRow, TopoEdgeRow, TopoNodeRow):
                await s.execute(delete(table))
            s.add_all([TopoNodeRow(id=n.id, type=n.type, name=n.name, aliases=n.aliases, env=n.env,
                                   parent=n.parent, description=n.description, updated_by=updated_by)
                       for n in topo.nodes()])
            s.add_all([TopoEdgeRow(from_id=e.from_id, to_id=e.to_id, protocol=e.protocol, timeout=e.timeout,
                                   route_rule=e.route_rule, description=e.description, updated_by=updated_by)
                       for e in topo.edges()])
            s.add_all([TopoPathRow(id=p.id, entry=p.entry, endpoint=p.endpoint, hops=p.hops)
                       for p in topo.paths()])

    async def load(self) -> Topology:
        async with self._sm() as s:
            nodes = (await s.scalars(select(TopoNodeRow).order_by(TopoNodeRow.id))).all()
            edges = (await s.scalars(select(TopoEdgeRow).order_by(TopoEdgeRow.id))).all()
            paths = (await s.scalars(select(TopoPathRow).order_by(TopoPathRow.id))).all()
        return Topology(
            nodes=[Node(id=r.id, type=r.type, name=r.name, aliases=r.aliases, env=r.env, parent=r.parent,
                        description=r.description) for r in nodes],
            edges=[Edge(from_id=r.from_id, to_id=r.to_id, protocol=r.protocol, timeout=r.timeout,
                        route_rule=r.route_rule, description=r.description) for r in edges],
            paths=[PathDef(id=r.id, entry=r.entry, endpoint=r.endpoint, hops=r.hops) for r in paths],
        )
