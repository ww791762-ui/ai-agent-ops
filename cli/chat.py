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


def _wait(client: httpx.Client, run_id: str, timeout_s: float = 300, interval_s: float = 1,
          sleep=time.sleep, clock=time.monotonic) -> dict | None:
    """轮询 Run 直到离开 queued/running；超时、非 200 或响应格式不对时打印提示并返回 None。"""
    deadline = clock() + timeout_s
    while True:
        r = client.get(f"/api/v1/runs/{run_id}")
        if r.status_code != 200:
            print(f"\n查询 Run 状态失败（HTTP {r.status_code}）：{r.text[:200]}")
            return None
        try:
            run = r.json()
            status = run["status"]
        except (ValueError, KeyError, TypeError):
            print(f"\n服务端返回的 Run 状态格式不正确：{r.text[:200]}")
            return None
        if status not in ("queued", "running"):
            print()
            return run
        if clock() >= deadline:
            print(f"\n等待超时（{timeout_s:.0f} 秒），Run {run_id} 仍在执行，可稍后查询 /api/v1/runs/{run_id}")
            return None
        print(".", end="", flush=True)
        sleep(interval_s)


def _ask(client: httpx.Client, session_id: str | None, msg: str) -> str | None:
    """发送一条消息并输出结果，返回（可能更新后的）session_id。"""
    r = client.post("/api/v1/chat", json={"session_id": session_id, "message": msg})
    if r.status_code == 409:
        print(r.json()["detail"])
        return session_id
    r.raise_for_status()
    session_id = r.json()["session_id"]
    run = _wait(client, r.json()["run_id"])
    if run is None:
        return session_id
    if run["status"] == "waiting_user":
        print(f"Agent> {run['question']}")
    elif run["status"] in ("completed", "partial"):
        print(render_report(run["report"]))
        if run["status"] == "partial":
            print("\n（部分结果：" + "；".join(run["partial_reasons"]) + "）")
    else:
        print(f"Agent> 执行失败：{run.get('error')}", file=sys.stderr)
    return session_id


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
            try:
                session_id = _ask(client, session_id, msg)
            except httpx.HTTPError as e:
                print(f"请求失败：{type(e).__name__}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
