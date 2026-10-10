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


def test_runner_now_is_rendered_in_shanghai_regardless_of_host_tz():
    # Prompt 声明 {{now}} 是 Asia/Shanghai；宿主机时区为 UTC 时也不能把 UTC 墙上时间交给模型
    from opsagent.runner.runner import local_now_iso

    assert local_now_iso(datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)) == "2026-10-10T09:00:00+08:00"


@pytest.mark.parametrize("text", ['示例 {"a": "b"}', "第一行\n第二行里有字面 \\n 不动"])
def test_intent_reply_keeps_legitimate_text(text):
    assert IntentResult(intent="out_of_scope", reply=text).reply == text
