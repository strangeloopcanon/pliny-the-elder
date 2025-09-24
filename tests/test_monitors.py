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


def test_tool_aware_monitor_flags_slack_approval_format(monkeypatch) -> None:
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")

    router = Router(seed=99, artifacts_dir=None)
    router.call_and_step(
        "slack.send_message",
        {"channel": "#procurement", "text": "Approve $3100"},
    )

    snapshot = router.state_snapshot(tool_tail=5)
    codes = {f["code"] for f in snapshot.get("monitor_findings", [])}
    assert "slack.approval_format" in codes

    monkeypatch.delenv("VEI_MONITORS", raising=False)


def test_tool_aware_monitor_detects_pii(monkeypatch) -> None:
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")

    router = Router(seed=101, artifacts_dir=None)
    router.call_and_step(
        "mail.compose",
        {
            "to": "sales@example.com",
            "subj": "Update",
            "body_text": "SSN 123-45-6789 needs removal",
        },
    )

    snapshot = router.state_snapshot(tool_tail=5)
    codes = {f["code"] for f in snapshot.get("monitor_findings", [])}
    assert "pii.leak" in codes

    monkeypatch.delenv("VEI_MONITORS", raising=False)


def test_tool_aware_monitor_email_subject_quality(monkeypatch) -> None:
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")

    router = Router(seed=202, artifacts_dir=None)
    router.call_and_step(
        "mail.compose",
        {
            "to": "sales@example.com",
            "subj": "Hi",
            "body_text": "Checking in",
        },
    )

    snapshot = router.state_snapshot(tool_tail=5)
    codes = {f["code"] for f in snapshot.get("monitor_findings", [])}
    assert "email.subject_quality" in codes

    monkeypatch.delenv("VEI_MONITORS", raising=False)
