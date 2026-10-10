from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), default="cli")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    intent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    skill_md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    partial_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EvidenceRow(Base):
    __tablename__ = "evidences"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"))
    tool: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    redaction_stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReportRow(Base):
    __tablename__ = "reports"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    content: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TopoNodeRow(Base):
    __tablename__ = "topo_nodes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    env: Mapped[str] = mapped_column(String(32), default="prod")
    parent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TopoEdgeRow(Base):
    __tablename__ = "topo_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_id: Mapped[str] = mapped_column(String(64))
    to_id: Mapped[str] = mapped_column(String(64))
    protocol: Mapped[str] = mapped_column(String(32), default="http")
    timeout: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route_rule: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TopoPathRow(Base):
    __tablename__ = "topo_paths"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry: Mapped[str] = mapped_column(String(64))
    endpoint: Mapped[str] = mapped_column(String(64))
    hops: Mapped[list] = mapped_column(JSONB)


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(128), default="")
    result: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
