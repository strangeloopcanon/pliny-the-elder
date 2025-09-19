from __future__ import annotations

import json
from pathlib import Path
import typer

from vei.score_core import compute_score

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

    mode = success_mode.lower().strip()
    if mode not in {"email", "full"}:
        raise typer.BadParameter("success_mode must be 'email' or 'full'")

    score_obj = compute_score(artifacts_dir, success_mode=mode)
    typer.echo(json.dumps(score_obj, indent=2))


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


score = app


if __name__ == "__main__":
    app()
