from __future__ import annotations

import json
from pathlib import Path

import typer

from vei.data.rollout import rollout_procurement


app = typer.Typer(add_completion=False)


@app.command()
def procurement(
    episodes: int = typer.Option(1, help="Number of scripted episodes"),
    seed: int = typer.Option(42042, help="Base RNG seed"),
    output: Path = typer.Option(Path("rollout.json"), help="Output dataset path"),
) -> None:
    dataset = rollout_procurement(episodes=episodes, seed=seed)
    text = json.dumps(dataset.model_dump(), indent=2)
    output.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {len(dataset.events)} events to {output}")


if __name__ == "__main__":
    app()
