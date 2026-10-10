from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from opsagent.runner.runner import SessionBusy


class ChatIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    session_id: str
    run_id: str


def create_app(lifespan=None) -> FastAPI:
    app = FastAPI(title="ops-agent", lifespan=lifespan)

    @app.post("/api/v1/chat", status_code=202, response_model=ChatOut)
    async def chat(body: ChatIn, request: Request) -> ChatOut:
        try:
            sid, rid = await request.app.state.c.runner.submit(body.session_id, body.message)
        except SessionBusy:
            raise HTTPException(409, "该会话还有问题正在处理，请稍后再试")
        return ChatOut(session_id=sid, run_id=rid)

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict:
        runs = request.app.state.c.runs
        run = await runs.get(run_id)
        if run is None:
            raise HTTPException(404, "Run 不存在")
        skill = {"id": run.skill_id, "version": run.skill_version, "md5": run.skill_md5} if run.skill_id else None
        return {"run_id": run.id, "session_id": run.session_id, "status": run.status,
                "question": run.pending_question, "intent": run.intent, "skill": skill,
                "step_count": run.step_count, "partial_reasons": run.partial_reasons, "error": run.error,
                "report": await runs.report(run_id)}

    @app.get("/api/v1/evidences/{evidence_id}")
    async def get_evidence(evidence_id: str, request: Request) -> dict:
        ev = await request.app.state.c.recorder.get_evidence(evidence_id)
        if ev is None:
            raise HTTPException(404, "证据不存在")
        return ev

    return app
