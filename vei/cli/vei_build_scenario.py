from __future__ import annotations

import json
from pathlib import Path
import typer

app = typer.Typer(add_completion=False)


@app.command()
def build(out: Path = typer.Option(..., exists=False, file_okay=False, dir_okay=True, writable=True)) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sample = {
        "budget_cap_usd": 3500,
        "derail_prob": 0.1,
        "slack_initial_message": "Reminder: citations required for any request over $2k.",
        "vendor_reply_variants": [
            "Thanks — Price: $3199, ETA: 5-7 business days.",
            "> On Mon, we received your request\nPRICE: USD 3,199\nEta: within 5-7 business days\n--\nBest, MacroCompute",
            "quote attached (inline): total: $3,199.00, ETA: 5 business days. Regards, Sales",
            "PRICE - $3199; eta: approx. 1 week\n\n\nJohn Doe\nSales Representative\nMacroCompute",
        ],
        "browser_nodes": None,
    }
    (out / "scenario.json").write_text(json.dumps(sample, indent=2), encoding="utf-8")
    typer.echo(f"Scenario written to {out}")


if __name__ == "__main__":
    app()

