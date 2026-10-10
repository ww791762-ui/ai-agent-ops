from cli.chat import render_report


def test_render_report_sections():
    text = render_report({
        "summary": "Kong → b 服务这一跳异常",
        "paths": [["proxy", "F5 vip-01", "Kong", "b 服务 /api/pay"]],
        "hops": [{"node": "Kong", "status": "abnormal", "observation": "upstream P99 3.1s", "evidence_ids": ["ev-3"]},
                 {"node": "proxy", "status": "normal", "observation": "", "evidence_ids": []}],
        "findings": [], "hypotheses": [{"cause": "连接池过小", "support": ["ev-5"], "against": [], "confidence": "high"}],
        "missing_evidence": ["DB 慢查询日志"], "suggestions": ["回滚连接池配置"], "needs_human": False,
        "assumptions": ["未给出环境，默认使用 prod"], "dropped_claims": 1,
    })
    assert "Kong → b 服务这一跳异常" in text
    assert "proxy → F5 vip-01 → Kong → b 服务 /api/pay" in text
    assert "✗ Kong" in text and "[ev-3]" in text and "✓ proxy" in text
    assert "连接池过小" in text and "DB 慢查询日志" in text and "回滚连接池配置" in text
    assert "默认使用 prod" in text and "1 条结论因引用了不存在的证据被移除" in text


import httpx  # noqa: E402

from cli.chat import _wait  # noqa: E402


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_wait_returns_when_run_leaves_running():
    states = iter(["queued", "running", "completed"])

    def handler(req):
        return httpx.Response(200, json={"status": next(states), "report": {"summary": "ok"}})

    run = _wait(client_for(handler), "run-1", sleep=lambda s: None)
    assert run["status"] == "completed"


def test_wait_gives_up_after_overall_timeout(capsys):
    t = [0.0]

    def sleep(s):
        t[0] += s

    run = _wait(client_for(lambda req: httpx.Response(200, json={"status": "running"})), "run-1",
                timeout_s=5, sleep=sleep, clock=lambda: t[0])
    assert run is None and "超时" in capsys.readouterr().out


def test_wait_handles_non_200(capsys):
    run = _wait(client_for(lambda req: httpx.Response(500, text="boom")), "run-1", sleep=lambda s: None)
    assert run is None and "500" in capsys.readouterr().out


def test_wait_handles_missing_status_and_non_json(capsys):
    assert _wait(client_for(lambda req: httpx.Response(200, json={"detail": "x"})), "r", sleep=lambda s: None) is None
    assert _wait(client_for(lambda req: httpx.Response(200, text="<html>")), "r", sleep=lambda s: None) is None
    assert capsys.readouterr().out


def test_main_continues_after_http_error(monkeypatch, capsys):
    import cli.chat as chat

    inputs = iter(["第一个问题", "第二个问题", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    posts = []

    def handler(req):
        if req.method == "POST":
            posts.append(req)
            if len(posts) == 1:
                raise httpx.ConnectError("refused")
            return httpx.Response(202, json={"session_id": "s-1", "run_id": "run-1"})
        return httpx.Response(200, json={"status": "waiting_user", "question": "哪个环境？"})

    real_client = httpx.Client
    monkeypatch.setattr(chat.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), base_url="http://test"))
    chat.main()
    out = capsys.readouterr()
    assert len(posts) == 2 and "哪个环境？" in out.out
