from __future__ import annotations

from vei.router.core import Router


def test_slack_fetch_thread_numeric_ordering():
    r = Router(seed=123, artifacts_dir=None)
    ch = "#procurement"

    # Send a root message
    root = r.call_and_step("slack.send_message", {"channel": ch, "text": "Initial request"})
    root_ts = root["ts"]

    # Send a few replies in the thread
    r.call_and_step("slack.send_message", {"channel": ch, "text": "Follow-up A", "thread_ts": root_ts})
    r.call_and_step("slack.send_message", {"channel": ch, "text": "Follow-up B", "thread_ts": root_ts})
    r.call_and_step("slack.send_message", {"channel": ch, "text": "Follow-up C", "thread_ts": root_ts})

    # Fetch thread and verify non-decreasing numeric ordering of ts
    thread = r.call_and_step("slack.fetch_thread", {"channel": ch, "thread_ts": root_ts})
    ts_values = [int(m["ts"]) for m in thread["messages"]]
    assert ts_values == sorted(ts_values)

