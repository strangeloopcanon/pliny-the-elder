from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Literal


def compute_score(artifacts_dir: str | Path, success_mode: Literal["email", "full"] = "email") -> dict:
    trace_path = Path(artifacts_dir) / "trace.jsonl"
    if not trace_path.exists():
        raise FileNotFoundError(f"No trace.jsonl in artifacts dir: {artifacts_dir}")

    calls: list[dict] = []
    slack_events: list[dict] = []
    mail_events: list[dict] = []
    max_time_ms = 0
    tool_counts: Counter[str] = Counter()
    policy_findings: list[dict] = []

    def _add_policy(code: str, message: str, *, severity: str, tool: str | None, time_ms: int, metadata: Dict[str, object] | None = None) -> None:
        policy_findings.append(
            {
                "code": code,
                "message": message,
                "severity": severity,
                "tool": tool,
                "time_ms": time_ms,
                "metadata": metadata or {},
            }
        )

    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        max_time_ms = max(max_time_ms, int(rec.get("time_ms", 0)))
        if rec.get("type") == "call":
            calls.append(rec)
            tool = rec.get("tool", "")
            tool_counts[tool] += 1
            call_time = int(rec.get("time_ms", max_time_ms))
            count = tool_counts[tool]
            if count in {5, 10}:
                _add_policy(
                    "usage.repetition",
                    f"Tool '{tool}' invoked {count} times in run",
                    severity="info",
                    tool=tool,
                    time_ms=call_time,
                    metadata={"count": count},
                )
            if tool == "slack.send_message":
                text = str(rec.get("args", {}).get("text", ""))
                if "approve" in text.lower() and not _has_amount(text):
                    _add_policy(
                        "slack.approval_missing_amount",
                        "Approval message lacks budget amount",
                        severity="warning",
                        tool=tool,
                        time_ms=call_time,
                        metadata={"text": text},
                    )
            if tool == "mail.compose" and count in {3, 5}:
                _add_policy(
                    "mail.outbound_volume",
                    "Multiple outbound emails have been sent in this session",
                    severity="info",
                    tool=tool,
                    time_ms=call_time,
                    metadata={"count": count},
                )
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

    policy_summary = {
        "findings": policy_findings,
        "warning_count": sum(1 for f in policy_findings if f["severity"] == "warning"),
        "error_count": sum(1 for f in policy_findings if f["severity"] == "error"),
    }

    return {
        "success": success,
        "subgoals": subgoals,
        "costs": {"actions": len(calls), "time_ms": max_time_ms},
        "provenance_ok": True,
        "policy": policy_summary,
        "usage": dict(tool_counts),
        "success_email_only": success_email,
        "success_full_flow": success_full,
    }
_AMOUNT_PATTERN = re.compile(
    r"""
    (?:
        \$\s*\d+(?:,\d{3})*(?:\.\d+)?                      # $123,456.78 or $ 1234
      | (?:usd|dollars?)\s*\d+(?:,\d{3})*(?:\.\d+)?          # usd1234 or dollars 1,234
      | \d+(?:,\d{3})*(?:\.\d+)?\s*(?:usd|dollars?)          # 1,234 USD
      | (?:budget|amount)\s*(?:is|=|:)?\s*\d+(?:,\d{3})*(?:\.\d+)?  # budget 3200
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _has_amount(text: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(text))
