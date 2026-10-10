# src/opsagent/agent/nodes/finalize.py
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..deps import Deps
from ..llm import StructuredOutputError
from ..prompting import render
from ..schemas import Report
from ..transcript import render_transcript


def drop_unknown_evidence(report: Report, known: set[str]) -> tuple[Report, int]:
    def ok(ids: list[str]) -> bool:
        return all(i in known for i in ids)

    hops = [h for h in report.hops if ok(h.evidence_ids)]
    findings = [f for f in report.findings if ok(f.evidence_ids)]
    hypotheses = [h for h in report.hypotheses if ok(h.support) and ok(h.against)]
    dropped = (len(report.hops) - len(hops)) + (len(report.findings) - len(findings)) \
        + (len(report.hypotheses) - len(hypotheses))
    return report.model_copy(update={"hops": hops, "findings": findings, "hypotheses": hypotheses}), dropped


def make_finalize(deps: Deps):
    async def finalize(state: dict) -> dict:
        intent = state.get("intent") or {}
        partial = list(state.get("partial_reasons", []))
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            partial.append("达到步数上限，基于已有证据输出")

        if intent.get("intent") == "out_of_scope":
            report = Report(summary=intent.get("reply") or "当前版本只支持只读的查询和排查，无法执行该操作。")
        elif state.get("unresolved"):
            report = Report(summary="无法确定要排查的对象：" + "；".join(state["unresolved"]), needs_human=True)
        else:
            try:
                report = await deps.llm.structured(
                    [SystemMessage(render(deps.store.prompt("ops.report").template)),
                     HumanMessage(render_transcript(state))], Report)
            except StructuredOutputError:
                last = next((m.content for m in reversed(messages)
                             if isinstance(m, AIMessage) and m.content), "")
                report = Report(summary=str(last) or "未能生成结构化报告", needs_human=not last)
                partial.append("报告格式校验失败，输出为纯文本")

        report, dropped = drop_unknown_evidence(report, set(state.get("evidence_ids", [])))
        report = report.model_copy(update={"dropped_claims": dropped,
                                           "assumptions": [*state.get("assumptions", []), *report.assumptions]})
        redacted = deps.store.redactor().with_salt(state["run_id"]).redact_obj(report.model_dump(mode="json"))
        history = [*state.get("history", []), {"question": state["question"], "answer": redacted["summary"]}][-5:]
        return {"report": redacted, "partial_reasons": partial, "history": history}

    return finalize
