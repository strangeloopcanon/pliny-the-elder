from __future__ import annotations

import json
from pathlib import Path
import os

import typer

from vei.behavior import ScriptedProcurementPolicy
from vei.data.models import VEIDataset
from vei.router.core import Router
from vei.score_core import compute_score
from vei.rl.policy_bc import BCPPolicy, run_policy


app = typer.Typer(add_completion=False)


@app.command()
def scripted(
    seed: int = typer.Option(42042, help="Router seed"),
    dataset: Path = typer.Option(Path("-"), help="Optional dataset JSON for replay"),
    artifacts: Path = typer.Option(Path("_vei_out/eval"), help="Artifacts directory"),
) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    if dataset != Path("-"):
        typer.echo(f"loading dataset {dataset}")
    router = Router(seed=seed, artifacts_dir=str(artifacts), scenario=None)
    if dataset != Path("-"):
        data = json.loads(dataset.read_text(encoding="utf-8"))
        ds = VEIDataset.model_validate(data)
        from vei.world.replay import ReplayAdapter

        adapter = ReplayAdapter(router.bus, ds.events)
        adapter.prime()

    policy = ScriptedProcurementPolicy(router)
    policy.run()

    score = compute_score(artifacts, success_mode="email")
    score_path = artifacts / "score.json"
    score_path.write_text(json.dumps(score, indent=2), encoding="utf-8")
    typer.echo(json.dumps(score, indent=2))


@app.command()
def bc(
    model: Path = typer.Option(..., "--model", "-m", exists=True, readable=True, help="Trained BC policy"),
    seed: int = typer.Option(42042, help="Router seed"),
    dataset: Path = typer.Option(Path("-"), help="Optional dataset JSON for replay"),
    artifacts: Path = typer.Option(Path("_vei_out/eval_bc"), help="Artifacts directory"),
    max_steps: int = typer.Option(12, help="Max policy steps"),
) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    previous_dataset = os.environ.get("VEI_DATASET")
    try:
        if dataset != Path("-"):
            os.environ["VEI_DATASET"] = str(dataset)
        elif "VEI_DATASET" in os.environ:
            del os.environ["VEI_DATASET"]
        router = Router(seed=seed, artifacts_dir=str(artifacts))
    finally:
        if previous_dataset is not None:
            os.environ["VEI_DATASET"] = previous_dataset
        elif "VEI_DATASET" in os.environ and dataset != Path("-"):
            del os.environ["VEI_DATASET"]
    policy = BCPPolicy.load(model)
    transcript = run_policy(router, policy, max_steps=max_steps)
    (artifacts / "transcript.json").write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    score = compute_score(artifacts, success_mode="email")
    (artifacts / "score.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
    typer.echo(json.dumps(score, indent=2))


if __name__ == "__main__":
    app()
