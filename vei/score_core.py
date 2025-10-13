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
    doc_logged = False
    ticket_updated = False
    crm_logged = False
    approval_with_amount = False
    vendor_reply_time_ms: int | None = None
    crm_log_time_ms: int | None = None
    price_pat = re.compile(r"\b(?:price|total)\s*(?::|-)\s*(?:USD|US\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", re.I)
    eta_pat = re.compile(r"\beta\s*(?::|-)\s*([^\n]+)", re.I)

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
            args = rec.get("args", {}) or {}
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
                text = str(args.get("text", ""))
                lowered = text.lower()
                if "approve" in lowered and _has_amount(text):
                    approval_with_amount = True
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
            if tool in {"docs.create", "docs.update"}:
                doc_logged = True
                doc_text = " ".join(str(args.get(field, "")) for field in ("title", "body"))
                if doc_text and not (_has_amount(doc_text) or "quote" in doc_text.lower() or "macrobook" in doc_text.lower()):
                    _add_policy(
                        "docs.missing_quote_details",
                        "Quote document created/updated without pricing context",
                        severity="warning",
                        tool=tool,
                        time_ms=call_time,
                        metadata={"title": args.get("title"), "doc_id": args.get("doc_id")},
                    )
            if tool in {"tickets.update", "tickets.transition"}:
                ticket_updated = True
                ticket_id = args.get("ticket_id")
                if not ticket_id:
                    _add_policy(
                        "tickets.missing_id",
                        "Ticket update missing ticket_id",
                        severity="error",
                        tool=tool,
                        time_ms=call_time,
                        metadata={},
                    )
                if tool == "tickets.update" and not any(args.get(field) for field in ("description", "assignee")):
                    _add_policy(
                        "tickets.empty_update",
                        "tickets.update invoked without description or assignee payload",
                        severity="warning",
                        tool=tool,
                        time_ms=call_time,
                        metadata={"ticket_id": ticket_id},
                    )
            if tool == "crm.log_activity":
                crm_logged = True
                crm_log_time_ms = call_time
                note = str(args.get("note", ""))
                if note:
                    if not _has_amount(note):
                        _add_policy(
                            "crm.note_missing_amount",
                            "CRM note lacks pricing detail",
                            severity="warning",
                            tool=tool,
                            time_ms=call_time,
                            metadata={"note": note},
                        )
                    if not _has_eta(note):
                        _add_policy(
                            "crm.note_missing_eta",
                            "CRM note missing ETA or delivery commitment",
                            severity="warning",
                            tool=tool,
                            time_ms=call_time,
                            metadata={"note": note},
                        )
                else:
                    _add_policy(
                        "crm.note_missing_body",
                        "CRM note logged without content",
                        severity="error",
                        tool=tool,
                        time_ms=call_time,
                        metadata={},
                    )
            if tool in {"crm.associate_contact_company", "crm.create_contact", "crm.create_company"} and not args:
                _add_policy(
                    "crm.payload_missing",
                    f"{tool} invoked without payload",
                    severity="warning",
                    tool=tool,
                    time_ms=call_time,
                    metadata={},
                )
        elif rec.get("type") == "event":
            if rec.get("target") == "slack":
                slack_events.append(rec)
            if rec.get("target") == "mail":
                mail_events.append(rec)
                body = rec.get("payload", {}).get("body_text", "")
                if vendor_reply_time_ms is None and body and price_pat.search(body) and eta_pat.search(body):
                    vendor_reply_time_ms = int(rec.get("time_ms", 0))

    subgoals = {
        "citations": 0,
        "approval": 0,
        "approval_with_amount": 0,
        "email_sent": 0,
        "email_parsed": 0,
        "doc_logged": 0,
        "ticket_updated": 0,
        "crm_logged": 0,
    }

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
    if approval_with_amount:
        subgoals["approval_with_amount"] = 1

    for e in mail_events:
        body = e.get("payload", {}).get("body_text", "")
        if body and price_pat.search(body) and eta_pat.search(body):
            subgoals["email_parsed"] = 1
            break
    if doc_logged:
        subgoals["doc_logged"] = 1
    if ticket_updated:
        subgoals["ticket_updated"] = 1
    if crm_logged:
        subgoals["crm_logged"] = 1

    success_email = bool(subgoals["email_parsed"])
    success_full = all(subgoals.values())
    mode = (success_mode or "email").lower().strip()
    if mode not in {"email", "full"}:
        mode = "email"
    success = success_email if mode == "email" else success_full

    if not doc_logged:
        _add_policy(
            "docs.quote_missing",
            "No docs.create/docs.update call observed; quote was not captured in Docs",
            severity="warning",
            tool=None,
            time_ms=max_time_ms,
            metadata={},
        )
    if not ticket_updated:
        _add_policy(
            "tickets.update_missing",
            "No tickets.update/transition call observed; tickets were left stale",
            severity="warning",
            tool=None,
            time_ms=max_time_ms,
            metadata={},
        )
    if vendor_reply_time_ms is not None:
        if crm_log_time_ms is None:
            _add_policy(
                "crm.note_absent",
                "Vendor quote arrived but no CRM log was recorded",
                severity="error",
                tool=None,
                time_ms=max_time_ms,
                metadata={"vendor_reply_ms": vendor_reply_time_ms},
            )
        else:
            latency_ms = crm_log_time_ms - vendor_reply_time_ms
            if latency_ms > 60000:
                _add_policy(
                    "sla.crm_followup_latency",
                    f"CRM note logged after {latency_ms/1000:.1f}s (>60s SLA)",
                    severity="warning",
                    tool="crm.log_activity",
                    time_ms=crm_log_time_ms,
                    metadata={"latency_ms": latency_ms},
                )

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


_ETA_PATTERN = re.compile(
    r"""
    (?:
        \beta[:\s-]*(?:within\s*)?\d+\s*(?:business\s*)?(?:day|days|hour|hours|week|weeks)\b
      | \bdelivery[:\s-]*(?:within\s*)?\d+\s*(?:business\s*)?(?:day|days|hour|hours|week|weeks)\b
      | \barriv(?:e|al)\b[:\s-]*(?:within\s*)?\d+\s*(?:business\s*)?(?:day|days|hour|hours|week|weeks)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _has_eta(text: str) -> bool:
    return bool(_ETA_PATTERN.search(text or ""))
