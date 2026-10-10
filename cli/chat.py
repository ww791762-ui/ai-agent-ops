"""终端聊天客户端。用法：uv run python -m cli.chat（服务地址由 OPSAGENT_API 指定，默认 http://127.0.0.1:8000）"""
import os
import sys
import time

import httpx

_MARK = {"abnormal": "✗", "normal": "✓", "unknown": "?"}


def _ids(ids: list[str]) -> str:
    return f" [{', '.join(ids)}]" if ids else ""


def render_report(r: dict) -> str:
    out = ["", "== 结论 ==", r["summary"]]
    for p in r.get("paths", []):
        out.append("链路：" + " → ".join(p))
    if r.get("hops"):
        out.append("\n== 逐跳 ==")
        out += [f" {_MARK.get(h['status'], '?')} {h['node']}：{h.get('observation', '')}{_ids(h.get('evidence_ids', []))}"
                for h in r["hops"]]
    if r.get("findings"):
        out.append("\n== 关键事实 ==")
        out += [f" - {f['fact']}{_ids(f.get('evidence_ids', []))}" for f in r["findings"]]
    if r.get("hypotheses"):
        out.append("\n== 可能原因 ==")
        for i, h in enumerate(r["hypotheses"], 1):
            against = f" 反驳{_ids(h['against'])}" if h.get("against") else ""
            out.append(f" {i}. {h['cause']}（{h.get('confidence', '')}） 支持{_ids(h.get('support', []))}{against}")
    for title, key in (("证据缺口", "missing_evidence"), ("建议", "suggestions"), ("默认假设", "assumptions")):
        if r.get(key):
            out.append(f"\n== {title} ==")
            out += [f" - {x}" for x in r[key]]
    if r.get("needs_human"):
        out.append("\n⚠ 建议人工接管")
    if r.get("dropped_claims"):
        out.append(f"\n（{r['dropped_claims']} 条结论因引用了不存在的证据被移除）")
    return "\n".join(out)


def _wait(client: httpx.Client, run_id: str) -> dict:
    while True:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            print()
            return run
        print(".", end="", flush=True)
        time.sleep(1)


def main() -> None:
    base = os.environ.get("OPSAGENT_API", "http://127.0.0.1:8000")
    session_id = None
    print("运维 Agent（输入 exit 退出）")
    with httpx.Client(base_url=base, timeout=10) as client:
        while True:
            try:
                msg = input("\n你> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not msg:
                continue
            if msg in ("exit", "quit"):
                break
            r = client.post("/api/v1/chat", json={"session_id": session_id, "message": msg})
            if r.status_code == 409:
                print(r.json()["detail"])
                continue
            r.raise_for_status()
            session_id = r.json()["session_id"]
            run = _wait(client, r.json()["run_id"])
            if run["status"] == "waiting_user":
                print(f"Agent> {run['question']}")
            elif run["status"] in ("completed", "partial"):
                print(render_report(run["report"]))
                if run["status"] == "partial":
                    print("\n（部分结果：" + "；".join(run["partial_reasons"]) + "）")
            else:
                print(f"Agent> 执行失败：{run.get('error')}", file=sys.stderr)


if __name__ == "__main__":
    main()
