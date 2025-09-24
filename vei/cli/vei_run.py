from __future__ import annotations

import os
import sys
import json
import typer

from vei.router.core import Router

app = typer.Typer(add_completion=False)


@app.command()
def run(seed: int = typer.Option(42042, help="Deterministic seed"), artifacts_dir: str | None = typer.Option(None, help="Artifacts output dir")) -> None:
    os.environ["VEI_SEED"] = str(seed)
    if artifacts_dir:
        os.environ["VEI_ARTIFACTS_DIR"] = artifacts_dir
    router = Router(seed=seed, artifacts_dir=artifacts_dir)
    # Simple interactive loop for manual testing
    typer.echo("VEI interactive. Type tool name and JSON args. Example: browser.read {}")
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            break
        if not raw:
            continue
        if raw in {"exit", "quit"}:
            break
        try:
            parts = raw.split(" ", 1)
            tool = parts[0]
            args = json.loads(parts[1]) if len(parts) > 1 else {}
            if tool == "vei.observe":
                res = router.observe().model_dump()
            else:
                res = router.call_and_step(tool, args)
            typer.echo(json.dumps(res, indent=2))
        except Exception as e:  # noqa: BLE001
            typer.echo(f"Error: {e}")
    router.trace.flush()


if __name__ == "__main__":
    app()

