from __future__ import annotations

import re
from typing import Any, Dict, List

from .models import MonitorFinding

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


class ToolAwareMonitor:
    """Heuristic monitor that inspects tool calls against simple policy hints."""

    name = "tool_aware"

    def __init__(self) -> None:
        self._call_counts: Dict[str, int] = {}

    def on_tool_call(
        self,
        *,
        tool: str,
        args: Dict[str, Any],
        result: Any,
        state_snapshot: Dict[str, Any],
    ) -> List[MonitorFinding]:
        findings: List[MonitorFinding] = []
        count = self._call_counts.get(tool, 0) + 1
        self._call_counts[tool] = count

        # Flag repetitive usage patterns (helps spot loops)
        if count in {5, 10}:
            findings.append(
                MonitorFinding(
                    monitor=self.name,
                    code="usage.repetition",
                    message=f"Tool '{tool}' invoked {count} times this run",
                    severity="info",
                    time_ms=int(state_snapshot.get("time_ms", 0)),
                    tool=tool,
                    metadata={"count": count},
                )
            )

        if tool == "slack.send_message":
            text = str(args.get("text", ""))
            if "approve" in text.lower() and not _has_amount(text):
                findings.append(
                    MonitorFinding(
                        monitor=self.name,
                        code="slack.approval_missing_amount",
                        message="Approval message lacks a budget amount",
                        severity="warning",
                        time_ms=int(state_snapshot.get("time_ms", 0)),
                        tool=tool,
                        metadata={"text": text},
                    )
                )

        if tool == "mail.compose":
            deliveries = state_snapshot.get("deliveries", {})
            mail_delivered = int(deliveries.get("mail", 0))
            if mail_delivered >= 3:
                findings.append(
                    MonitorFinding(
                        monitor=self.name,
                        code="mail.outbound_volume",
                        message="Multiple outbound emails sent; ensure recipients are intended.",
                        severity="info",
                        time_ms=int(state_snapshot.get("time_ms", 0)),
                        tool=tool,
                        metadata={"mail_delivered": mail_delivered},
                    )
                )

        return findings


def _has_amount(text: str) -> bool:
    return bool(_AMOUNT_PATTERN.search(text))
