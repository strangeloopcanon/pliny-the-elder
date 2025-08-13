from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal


def compute_score(artifacts_dir: str | Path, success_mode: Literal["email", "full"] = "email") -> dict:
    trace_path = Path(artifacts_dir) / "trace.jsonl"
    if not trace_path.exists():
        raise FileNotFoundError(f"No trace.jsonl in artifacts dir: {artifacts_dir}")

    calls: list[dict] = []
    slack_events: list[dict] = []
    mail_events: list[dict] = []

    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if rec.get("type") == "call":
            calls.append(rec)
        elif rec.get("type") == "event":
            if rec.get("target") == "slack":
                slack_events.append(rec)
            if rec.get("target") == "mail":
                mail_events.append(rec)

    subgoals = {"citations": 0, "approval": 0, "email_sent": 0, "email_parsed": 0}

    if any(c.get("tool") == "browser.read" for c in calls):
        subgoals["citations"] = 1
    if any(c.get("tool") == "mail.compose" for c in calls):
        subgoals["email_sent"] = 1
    if any(
        ":white_check_mark:" in (e.get("payload", {}).get("text", "")) or
        "approved" in (e.get("payload", {}).get("text", "").lower())
        for e in slack_events
    ):
        subgoals["approval"] = 1

    price_pat = re.compile(r"\b(?:price|total)\s*(?::|-)\s*(?:USD|US\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", re.I)
    eta_pat = re.compile(r"\beta\s*(?::|-)\s*([^\n]+)", re.I)
    for e in mail_events:
        body = e.get("payload", {}).get("body_text", "")
        if body and price_pat.search(body) and eta_pat.search(body):
            subgoals["email_parsed"] = 1
            break

    success_email = bool(subgoals["email_parsed"])
    success_full = all(subgoals.values())
    mode = (success_mode or "email").lower().strip()
    if mode not in {"email", "full"}:
        mode = "email"
    success = success_email if mode == "email" else success_full

    return {
        "success": success,
        "subgoals": subgoals,
        "costs": {"actions": len(calls)},
        "provenance_ok": True,
        "success_email_only": success_email,
        "success_full_flow": success_full,
    }


