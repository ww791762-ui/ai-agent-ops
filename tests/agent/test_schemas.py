from datetime import datetime, timedelta, timezone

import pytest

from opsagent.agent.schemas import IntentResult

CST = timezone(timedelta(hours=8))


@pytest.mark.parametrize("raw", ["2026-10-09T20:00:00", "2026-10-09T20:00:00Z", "2026-10-09T20:00:00+00:00",
                                 "2026-10-09T20:00:00+08:00"])
def test_intent_times_are_shanghai_wall_clock(raw):
    # glm-5.2 常把本地时间标成 UTC 或省略时区；约定时间字段一律是 Asia/Shanghai 的墙上时间
    r = IntentResult(intent="troubleshoot", time_from=raw, time_to=raw)
    assert r.time_from == datetime(2026, 10, 9, 20, 0, tzinfo=CST)
    assert r.time_to.utcoffset() == timedelta(hours=8)


def test_intent_reply_unescapes_literal_newlines_and_json_tail():
    r = IntentResult(intent="out_of_scope", reply='不能重启。\\n建议：\\n1. 确认状态。"}')
    assert r.reply == "不能重启。\n建议：\n1. 确认状态。"
