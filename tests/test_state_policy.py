from __future__ import annotations

from pathlib import Path

import os

from vei.router.core import Router


def test_policy_findings_persist(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("VEI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")
    router = Router(seed=1, artifacts_dir=None)

    router.call_and_step("slack.send_message", {"channel": "#procurement", "text": "Please approve"})

    snapshot = router.state_snapshot(tool_tail=5)
    policy_codes = {f["code"] for f in snapshot.get("policy_findings", [])}
    assert "slack.approval_missing_amount" in policy_codes

    monkeypatch.delenv("VEI_STATE_DIR", raising=False)
    monkeypatch.delenv("VEI_MONITORS", raising=False)


def test_policy_not_flagged_with_budget(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("VEI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")
    router = Router(seed=3, artifacts_dir=None)

    router.call_and_step(
        "slack.send_message",
        {"channel": "#procurement", "text": "Please approve; budget $3200."},
    )

    snapshot = router.state_snapshot(tool_tail=5)
    policy_codes = {f["code"] for f in snapshot.get("policy_findings", [])}
    assert "slack.approval_missing_amount" not in policy_codes

    monkeypatch.delenv("VEI_STATE_DIR", raising=False)
    monkeypatch.delenv("VEI_MONITORS", raising=False)


def test_policy_promote_env_overrides_severity(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("VEI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("VEI_MONITORS", "tool_aware")
    monkeypatch.setenv("VEI_POLICY_PROMOTE", "usage.repetition:error")

    router = Router(seed=2, artifacts_dir=None)
    for _ in range(5):
        router.call_and_step("browser.read", {})

    snapshot = router.state_snapshot(tool_tail=10)
    policy_entries = [p for p in snapshot.get("policy_findings", []) if p["code"] == "usage.repetition"]
    assert policy_entries, "Expected policy entry for usage.repetition"
    assert policy_entries[-1]["severity"] == "error"

    monkeypatch.delenv("VEI_STATE_DIR", raising=False)
    monkeypatch.delenv("VEI_MONITORS", raising=False)
    monkeypatch.delenv("VEI_POLICY_PROMOTE", raising=False)
