from __future__ import annotations

import json
from pathlib import Path
import typer

app = typer.Typer(add_completion=False)


def _load_trace(artifacts_dir: Path) -> list[dict]:
    p = artifacts_dir / "trace.jsonl"
    if not p.exists():
        raise typer.BadParameter("No trace.jsonl in artifacts dir")
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                ...
    return out


def _score_crm(records: list[dict]) -> dict:
    calls = [r for r in records if r.get("type") == "call"]
    # Identify main steps for lead→qualified opportunity
    contact_created = False
    company_created = False
    associated = False
    deal_created = False
    qualified = False
    first_touch_ms: int | None = None
    lead_created_ms: int | None = None
    consent_violations = 0

    for c in calls:
        tool = c.get("tool")
        resp = c.get("response", {})
        tms = c.get("time_ms")
        if tool in {"crm.create_contact", "hubspot.contacts.create", "salesforce.contact.create"}:
            contact_created = True
            lead_created_ms = tms if isinstance(tms, int) else lead_created_ms
        elif tool in {"crm.create_company", "hubspot.companies.create", "salesforce.account.create"}:
            company_created = True
        elif tool in {"crm.associate_contact_company", "hubspot.associations.contact_company", "salesforce.contact.link_account"}:
            associated = True if not resp.get("error") else associated
        elif tool in {"crm.create_deal", "hubspot.deals.create", "salesforce.opportunity.create"}:
            deal_created = True
        elif tool in {"crm.update_deal_stage", "hubspot.deals.update_stage", "salesforce.opportunity.update_stage"}:
            if (resp or {}).get("stage", "").lower() in {"qualified", "qualification", "sales qualified"}:
                qualified = True
        elif tool in {"crm.log_activity", "hubspot.activities.log", "salesforce.activity.log"}:
            if not resp or not resp.get("error"):
                if first_touch_ms is None and isinstance(tms, int):
                    first_touch_ms = tms
            else:
                if resp.get("error", {}).get("code") == "consent_violation":
                    consent_violations += 1

    # SLA: first touch within 1 day logical time (86_400_000 ms)
    sla_met = False
    if lead_created_ms is not None and first_touch_ms is not None:
        sla_met = (first_touch_ms - lead_created_ms) <= 86_400_000

    subgoals = {
        "contact_created": int(contact_created),
        "company_created": int(company_created),
        "associated": int(associated),
        "deal_created": int(deal_created),
        "qualified_stage": int(qualified),
        "first_touch_sla": int(sla_met),
        "consent_violations": consent_violations,
    }
    success = all([contact_created, company_created, associated, deal_created, qualified, sla_met]) and consent_violations == 0
    return {"success": success, "subgoals": subgoals}


@app.command(name="score-crm")
def score_crm(
    artifacts_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, readable=True),
) -> None:
    recs = _load_trace(artifacts_dir)
    out = _score_crm(recs)
    typer.echo(json.dumps(out, indent=2))


score = app


if __name__ == "__main__":
    app()

