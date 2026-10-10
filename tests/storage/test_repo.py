from pathlib import Path

import pytest
from sqlalchemy import select

from opsagent.storage.models import AuditRow
from opsagent.storage.repo import DbRecorder, RunRepo, TopologyRepo
from opsagent.topology.model import load_topology_yaml

pytestmark = pytest.mark.db


async def test_run_lifecycle(db_sm):
    runs = RunRepo(db_sm)
    await runs.create(run_id="run-1", session_id="s-1", question="q", prompt_versions={"prompts": {}})
    assert (await runs.active_run("s-1")).id == "run-1"
    await runs.mark_running("run-1")
    await runs.set_waiting("run-1", "哪个环境？")
    assert await runs.active_run("s-1") is None
    waiting = await runs.waiting_run("s-1")
    assert waiting.id == "run-1" and waiting.pending_question == "哪个环境？"

    await runs.mark_running("run-1")
    await runs.finish("run-1", status="completed", report={"summary": "ok"},
                      intent={"intent": "troubleshoot"},
                      skill={"id": "http_5xx", "version": "1.0.0", "md5": "abc"},
                      step_count=3, partial_reasons=[])
    run = await runs.get("run-1")
    assert run.status == "completed" and run.skill_id == "http_5xx"
    assert run.pending_question is None and run.step_count == 3
    assert await runs.report("run-1") == {"summary": "ok"}
    assert await runs.waiting_run("s-1") is None


async def test_recorder_evidence_and_audit(db_sm):
    await RunRepo(db_sm).create(run_id="run-2", session_id="s-2", question="q", prompt_versions={})
    rec = DbRecorder(db_sm)
    ev = await rec.record(run_id="run-2", tool="logs.search", args={"node_id": "svc-b"}, status="ok",
                          data={"lines": ["x"]}, redaction_stats={"phone": 1}, duration_ms=12,
                          error=None, make_evidence=True)
    assert ev.startswith("ev-")
    got = await rec.get_evidence(ev)
    assert got["content"] == {"lines": ["x"]} and got["run_id"] == "run-2" and got["tool"] == "logs.search"

    none = await rec.record(run_id="run-2", tool="shell.exec", args={}, status="denied", data=None,
                            redaction_stats={}, duration_ms=1, error="未注册的工具", make_evidence=False)
    assert none is None
    async with db_sm() as s:
        audits = (await s.scalars(select(AuditRow))).all()
    assert len(audits) == 1 and audits[0].result == "denied"


async def test_topology_roundtrip_idempotent(db_sm):
    topo = load_topology_yaml(Path("fixtures/topology.yaml").read_text(encoding="utf-8"))
    repo = TopologyRepo(db_sm)
    await repo.replace_all(topo, updated_by="test")
    await repo.replace_all(topo, updated_by="test")
    loaded = await repo.load()
    assert len(loaded.nodes()) == len(topo.nodes())
    assert sorted(p.path_id for p in loaded.trace("svc-c")) == ["c-ocr-direct", "c-ocr-via-proxy"]
    assert loaded.get("svc-b-pay").parent == "svc-b"


async def test_finish_does_not_overwrite_terminal_run(db_sm):
    runs = RunRepo(db_sm)
    await runs.create(run_id="run-t", session_id="s-t", question="q", prompt_versions={})
    await runs.mark_running("run-t")
    assert await runs.finish("run-t", status="failed", error="运行超时") is True
    assert await runs.finish("run-t", status="completed", report={"summary": "late"}) is False
    run = await runs.get("run-t")
    assert run.status == "failed" and run.error == "运行超时"
    assert await runs.report("run-t") is None


async def test_finish_twice_with_report_does_not_conflict(db_sm):
    runs = RunRepo(db_sm)
    await runs.create(run_id="run-r", session_id="s-r", question="q", prompt_versions={})
    await runs.finish("run-r", status="completed", report={"summary": "a"})
    assert await runs.finish("run-r", status="partial", report={"summary": "b"}) is False
    assert await runs.report("run-r") == {"summary": "a"}
