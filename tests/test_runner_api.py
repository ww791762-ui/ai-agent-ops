from datetime import UTC, datetime, timedelta

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from opsagent.agent.graph import build_graph
from opsagent.api.app import create_app
from opsagent.container import Container
from opsagent.runner.runner import Runner, SessionBusy
from opsagent.storage.models import EvidenceRow
from opsagent.storage.repo import DbRecorder, RunRepo
from tests.agent.test_graph import b_pay_script
from tests.helpers import make_deps

pytestmark = pytest.mark.db


async def setup(tmp_path, db_sm, script, clock=None):
    rec = DbRecorder(db_sm)
    deps, llm, _ = await make_deps(tmp_path, script, recorder=rec)
    runs = RunRepo(db_sm)
    runner = Runner(build_graph(deps, InMemorySaver()), runs, deps.store, clock=clock)
    app = create_app()
    app.state.c = Container(runner=runner, runs=runs, recorder=rec)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return runner, runs, client


async def test_chat_clarify_then_report(tmp_path, db_sm):
    runner, runs, client = await setup(tmp_path, db_sm, b_pay_script())
    r = await client.post("/api/v1/chat", json={"message": "b 服务支付接口昨晚开始变慢 token=abc123"})
    assert r.status_code == 202
    sid, rid = r.json()["session_id"], r.json()["run_id"]
    await runner.drain()

    run = (await client.get(f"/api/v1/runs/{rid}")).json()
    assert run["status"] == "waiting_user" and "环境" in run["question"]
    assert "abc123" not in (await runs.get(rid)).question  # 存库的问题已脱敏

    r2 = await client.post("/api/v1/chat", json={"session_id": sid, "message": "prod"})
    assert r2.status_code == 202 and r2.json()["run_id"] == rid  # 追问回答续接同一个 Run
    await runner.drain()

    run = (await client.get(f"/api/v1/runs/{rid}")).json()
    assert run["status"] == "completed" and run["skill"]["id"] == "http_5xx"
    assert run["report"]["summary"]
    # DbRecorder 的证据 ID 是随机生成的，脚本里写死的 ev-x 会被 finalize 剔除，所以证据 ID 从库里取
    async with db_sm() as s:
        ev_ids = (await s.scalars(select(EvidenceRow.id).where(EvidenceRow.run_id == rid))).all()
    assert len(ev_ids) == 6
    for ev_id in ev_ids:
        ev = await client.get(f"/api/v1/evidences/{ev_id}")
        assert ev.status_code == 200 and "eyJhbGci" not in ev.text and "13812341234" not in ev.text


async def test_unknown_run_and_evidence_404(tmp_path, db_sm):
    _, _, client = await setup(tmp_path, db_sm, [])
    assert (await client.get("/api/v1/runs/run-nope")).status_code == 404
    assert (await client.get("/api/v1/evidences/ev-nope")).status_code == 404


async def test_busy_session_returns_409(tmp_path, db_sm):
    runner, runs, client = await setup(tmp_path, db_sm, [])
    await runs.create(run_id="run-busy", session_id="s-busy", question="q", prompt_versions={})
    r = await client.post("/api/v1/chat", json={"session_id": "s-busy", "message": "再问一个"})
    assert r.status_code == 409
    with pytest.raises(SessionBusy):
        await runner.submit("s-busy", "x")


async def test_waiting_run_times_out_and_new_question_starts(tmp_path, db_sm):
    now = [datetime.now(UTC)]
    runner, runs, _ = await setup(tmp_path, db_sm, [*b_pay_script()[:1], *b_pay_script()[:1]],
                                  clock=lambda: now[0])
    sid, first = await runner.submit(None, "b 服务支付接口昨晚开始变慢")
    await runner.drain()
    assert (await runs.get(first)).status == "waiting_user"

    now[0] = now[0] + timedelta(minutes=31)
    _, second = await runner.submit(sid, "b 服务支付接口昨晚开始变慢")
    await runner.drain()
    assert second != first
    assert (await runs.get(first)).status == "cancelled"
    assert (await runs.get(second)).status == "waiting_user"


async def test_graph_exception_marks_failed(tmp_path, db_sm):
    runner, runs, _ = await setup(tmp_path, db_sm, [RuntimeError("模型挂了")])
    _, rid = await runner.submit(None, "b 服务支付接口昨晚开始变慢")
    await runner.drain()
    run = await runs.get(rid)
    assert run.status == "failed" and "模型挂了" in run.error
