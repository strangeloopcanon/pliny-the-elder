from __future__ import annotations

import os

from vei.router.core import Router


def test_tool_aware_monitor_flags_missing_budget(monkeypatch) -> None:
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")

    router = Router(seed=123, artifacts_dir=None)
    router.call_and_step(
        "slack.send_message",
        {"channel": "#procurement", "text": "Please approve the laptop purchase"},
    )

    snapshot = router.state_snapshot(tool_tail=5)
    findings = snapshot.get("monitor_findings", [])
    assert findings, "Expected monitor findings when monitor is enabled"
    codes = {f["code"] for f in findings}
    assert "slack.approval_missing_amount" in codes

    monkeypatch.delenv("VEI_MONITORS", raising=False)
