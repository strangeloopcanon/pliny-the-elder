from __future__ import annotations

import json
from dataclasses import asdict

import typer

from vei.world.compiler import compile_scene, load_scene_spec
from vei.world.scenarios import get_scenario, list_scenarios


app = typer.Typer(add_completion=False)


@app.command()
def list() -> None:  # noqa: A003 - CLI name
    cats = list_scenarios()
    for name in cats.keys():
        typer.echo(name)


@app.command()
def dump(name: str, indent: int = typer.Option(2, help="Pretty indent")) -> None:
    scen = get_scenario(name)
    typer.echo(json.dumps(asdict(scen), indent=indent))


@app.command()
def compile(path: str, indent: int = typer.Option(2, help="Pretty indent"), seed: int = typer.Option(42042, help="Seed for deterministic sampling")) -> None:
    spec = load_scene_spec(path)
    scen = compile_scene(spec, seed=seed)
    typer.echo(json.dumps(asdict(scen), indent=indent))


if __name__ == "__main__":
    app()
