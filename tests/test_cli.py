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
