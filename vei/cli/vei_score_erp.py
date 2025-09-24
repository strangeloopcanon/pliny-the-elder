from __future__ import annotations

import json
from pathlib import Path
import typer

app = typer.Typer(add_completion=False)


def _load_trace(artifacts_dir: Path) -> list[dict]:
    trace_path = artifacts_dir / "trace.jsonl"
    if not trace_path.exists():
        raise typer.BadParameter("No trace.jsonl in artifacts dir")
    records: list[dict] = []
    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            records.append(json.loads(raw))
        except Exception:
            continue
    return records


def _score_p2p(records: list[dict]) -> dict:
    calls = [r for r in records if r.get("type") == "call"]
    # Identify objects
    po_ids: set[str] = set()
    rcpt_ids: set[str] = set()
    inv_ids: set[str] = set()
    matched: bool = False
    paid: bool = False

    for c in calls:
        tool = c.get("tool")
        resp = c.get("response", {})
        if tool in {"erp.create_po", "xero.create_purchase_order", "netsuite.po.create", "dynamics.po.create", "quickbooks.purchaseorder.create"}:
            pid = (resp or {}).get("id") or (resp or {}).get("po_id")
            if pid:
                po_ids.add(str(pid))
        elif tool == "erp.receive_goods":
            rid = (resp or {}).get("id")
            if rid:
                rcpt_ids.add(str(rid))
        elif tool in {"erp.submit_invoice", "xero.create_invoice", "netsuite.invoice.create", "dynamics.invoice.create", "quickbooks.invoice.create"}:
            iid = (resp or {}).get("id")
            if iid:
                inv_ids.add(str(iid))
        elif tool == "erp.match_three_way":
            if (resp or {}).get("status") == "MATCH":
                matched = True
        elif tool in {"erp.post_payment", "xero.post_payment", "netsuite.payment.apply", "dynamics.payment.post", "quickbooks.payment.create"}:
            if (resp or {}).get("status") == "PAID":
                paid = True

    subgoals = {
        "po_created": int(bool(po_ids)),
        "goods_received": int(bool(rcpt_ids)),
        "invoice_submitted": int(bool(inv_ids)),
        "matched": int(matched),
        "paid": int(paid),
    }
    success = all(subgoals.values())
    return {"success": success, "subgoals": subgoals, "objects": {"pos": list(po_ids), "receipts": list(rcpt_ids), "invoices": list(inv_ids)}}


@app.command(name="score-erp")
def score_erp(
    artifacts_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, readable=True),
) -> None:
    recs = _load_trace(artifacts_dir)
    score = _score_p2p(recs)
    typer.echo(json.dumps(score, indent=2))


score = app


if __name__ == "__main__":
    app()

