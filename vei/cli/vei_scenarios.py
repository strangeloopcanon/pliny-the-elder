from __future__ import annotations

import json
from typing import Optional

import typer

from vei.world.scenarios import list_scenarios, get_scenario


app = typer.Typer(add_completion=False)


@app.command()
def list() -> None:  # noqa: A003 - CLI name
    cats = list_scenarios()
    for name in cats.keys():
        typer.echo(name)


@app.command()
def dump(name: str, indent: Optional[int] = typer.Option(2, help="Pretty indent")) -> None:
    scen = get_scenario(name)
    typer.echo(json.dumps(scen.__dict__, indent=indent))


if __name__ == "__main__":
    app()

