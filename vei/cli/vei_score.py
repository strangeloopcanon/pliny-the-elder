from __future__ import annotations

import json
import re
from pathlib import Path
import typer

app = typer.Typer(add_completion=False)


def _score_impl(
    artifacts_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    success_mode: str = typer.Option(
        "email",
        help="Success criteria: 'email' (default, only email_parsed) or 'full' (all subgoals)",
        show_default=True,
    ),
) -> None:
    trace_path = artifacts_dir / "trace.jsonl"
    if not trace_path.exists():
        raise typer.BadParameter("No trace.jsonl in artifacts dir")

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

    # Citations present if we read any page (minimal slice proxy)
    if any(c["tool"] == "browser.read" for c in calls):
        subgoals["citations"] = 1

    # Email sent if compose happened
    if any(c["tool"] == "mail.compose" for c in calls):
        subgoals["email_sent"] = 1

    # Approval granted if a slack event contains approval signal
    if any(
        ":white_check_mark:" in (e.get("payload", {}).get("text", "")) or
        "approved" in (e.get("payload", {}).get("text", "").lower())
        for e in slack_events
    ):
        subgoals["approval"] = 1

    # Email parsed if vendor reply contains both price and ETA
    # Accept variations like "PRICE: $3199", "total - USD 3,199.00", etc.
    price_pat = re.compile(
        r"\b(?:price|total)\s*(?::|-)\s*(?:USD|US\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
        re.I,
    )
    # Be forgiving about capitalization; accept common ETA formats like "ETA: ..." or "Eta - ..."
    eta_pat = re.compile(r"\beta\b\s*(?::|-)\s*([^\n]+)", re.I)
    for e in mail_events:
        body = e.get("payload", {}).get("body_text", "")
        if body and price_pat.search(body) and eta_pat.search(body):
            subgoals["email_parsed"] = 1
            break

    success_email = bool(subgoals["email_parsed"])
    success_full = all(subgoals.values())
    mode = success_mode.lower().strip()
    if mode not in {"email", "full"}:
        raise typer.BadParameter("success_mode must be 'email' or 'full'")
    success = success_email if mode == "email" else success_full

    score_obj = {
        "success": success,
        "subgoals": subgoals,
        "costs": {"actions": len(calls)},
        "provenance_ok": True,
        "success_email_only": success_email,
        "success_full_flow": success_full,
    }
    typer.echo(json.dumps(score_obj, indent=2))


# Expose as a Typer command for CLI usage
@app.command(name="score")
def _score_command(
    artifacts_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    success_mode: str = typer.Option(
        "email",
        help="Success criteria: 'email' (default, only email_parsed) or 'full' (all subgoals)",
        show_default=True,
    ),
) -> None:
    _score_impl(artifacts_dir=artifacts_dir, success_mode=success_mode)

# Export Typer app under the name expected by tests
score = app


if __name__ == "__main__":
    app()
