"""CLI for running frontier model evaluations with multi-dimensional scoring.

Usage:
    vei-eval-frontier --model gpt-5 --scenario f1_budget_reconciliation --max-steps 60
    vei-eval-frontier --model gpt-5 --scenario-set all_frontier --provider openai
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer

from vei.world.scenarios import list_scenarios
from vei.score_frontier import compute_frontier_score

app = typer.Typer(name="vei-eval-frontier", help="Run frontier model evaluations")


FRONTIER_SCENARIO_SETS = {
    "all_frontier": [
        "f1_budget_reconciliation",
        "f3_vague_urgent_request",
        "f4_contradictory_requirements",
        "f7_compliance_audit",
        "f9_cascading_failure",
        "f13_ethical_dilemma",
        "f14_data_privacy",
    ],
    "reasoning": [
        "f1_budget_reconciliation",
        "f4_contradictory_requirements",
    ],
    "safety": [
        "f13_ethical_dilemma",
        "f14_data_privacy",
    ],
    "expertise": [
        "f7_compliance_audit",
        "f9_cascading_failure",
    ],
}


@app.command(name="run")
def run_frontier_eval(
    model: str = typer.Option(..., help="Model name (e.g., gpt-5, claude-sonnet-4-5)"),
    scenario: Optional[str] = typer.Option(None, help="Single scenario to run (e.g., f1_budget_reconciliation)"),
    scenario_set: Optional[str] = typer.Option(None, help="Scenario set to run (all_frontier, reasoning, safety, expertise)"),
    provider: str = typer.Option("auto", help="LLM provider: openai, anthropic, google, openrouter, auto"),
    max_steps: int = typer.Option(80, help="Maximum steps per scenario"),
    artifacts_root: Path = typer.Option(Path("_vei_out/frontier_eval"), help="Root directory for artifacts"),
    seed: int = typer.Option(42042, help="Random seed for reproducibility"),
    use_llm_judge: bool = typer.Option(False, help="Use LLM-as-judge for communication quality scoring"),
    verbose: bool = typer.Option(False, help="Verbose output"),
) -> None:
    """Run frontier evaluation on specified scenarios.
    
    This command runs vei-llm-test for each scenario and computes multi-dimensional scores.
    """
    
    # Determine which scenarios to run
    scenarios_to_run = []
    
    if scenario:
        scenarios_to_run = [scenario]
    elif scenario_set:
        if scenario_set not in FRONTIER_SCENARIO_SETS:
            typer.echo(f"❌ Unknown scenario set: {scenario_set}", err=True)
            typer.echo(f"Available sets: {', '.join(FRONTIER_SCENARIO_SETS.keys())}", err=True)
            raise typer.Exit(1)
        scenarios_to_run = FRONTIER_SCENARIO_SETS[scenario_set]
    else:
        typer.echo("❌ Must specify either --scenario or --scenario-set", err=True)
        raise typer.Exit(1)
    
    # Validate scenarios exist
    available_scenarios = list_scenarios()
    for s in scenarios_to_run:
        if s not in available_scenarios:
            typer.echo(f"❌ Unknown scenario: {s}", err=True)
            raise typer.Exit(1)
    
    # Create artifacts root
    artifacts_root.mkdir(parents=True, exist_ok=True)
    
    # Generate run ID
    run_id = f"{model.replace('/', '_')}_{int(time.time())}"
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    typer.echo(f"🚀 Starting frontier evaluation: {len(scenarios_to_run)} scenarios")
    typer.echo(f"   Model: {model}")
    typer.echo(f"   Provider: {provider}")
    typer.echo(f"   Artifacts: {run_dir}")
    typer.echo("")
    
    # Run each scenario
    results = []
    
    for idx, scenario_name in enumerate(scenarios_to_run, 1):
        typer.echo(f"[{idx}/{len(scenarios_to_run)}] Running scenario: {scenario_name}")
        
        scenario_dir = run_dir / scenario_name
        scenario_dir.mkdir(parents=True, exist_ok=True)
        
        # Save scenario metadata
        scenario_obj = available_scenarios[scenario_name]
        metadata = getattr(scenario_obj, "metadata", {})
        with open(scenario_dir / "scenario_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        # Build task description from scenario metadata or use default
        task_desc = metadata.get("task_description", f"Complete the {scenario_name} scenario according to requirements.")
        
        # Run vei-llm-test
        cmd = [
            sys.executable, "-m", "vei.cli.vei_llm_test",
            "--model", model,
            "--provider", provider,
            "--max-steps", str(max_steps),
            "--artifacts", str(scenario_dir),
            "--seed", str(seed),
        ]
        
        # Set environment variable for scenario
        env = os.environ.copy()
        env["VEI_SCENARIO"] = scenario_name
        env["VEI_SEED"] = str(seed)
        
        if verbose:
            typer.echo(f"   Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=not verbose,
                text=True,
                timeout=600,  # 10 minute timeout per scenario
            )
            
            if result.returncode != 0 and not verbose:
                typer.echo(f"   ⚠️  Non-zero exit code: {result.returncode}")
                typer.echo(f"   stderr: {result.stderr[:500]}")
        
        except subprocess.TimeoutExpired:
            typer.echo(f"   ❌ Timeout after 10 minutes")
            continue
        except Exception as e:
            typer.echo(f"   ❌ Error: {e}")
            continue
        
        # Compute frontier score
        try:
            score = compute_frontier_score(scenario_dir, use_llm_judge=use_llm_judge)
            
            # Save score
            with open(scenario_dir / "frontier_score.json", "w") as f:
                json.dump(score, f, indent=2)
            
            # Display summary
            success_icon = "✅" if score.get("success") else "❌"
            composite = score.get("composite_score", 0.0)
            typer.echo(f"   {success_icon} Composite Score: {composite:.3f} | Steps: {score.get('steps_taken', 0)}")
            
            results.append({
                "scenario": scenario_name,
                "model": model,
                "provider": provider,
                "score": score,
            })
        
        except Exception as e:
            typer.echo(f"   ❌ Scoring error: {e}")
            results.append({
                "scenario": scenario_name,
                "model": model,
                "provider": provider,
                "score": {"success": False, "error": str(e)},
            })
        
        typer.echo("")
    
    # Save aggregate results
    aggregate_path = run_dir / "aggregate_results.json"
    with open(aggregate_path, "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    typer.echo("=" * 70)
    typer.echo(f"📊 Evaluation Complete: {run_id}")
    typer.echo("=" * 70)
    
    success_count = sum(1 for r in results if r["score"].get("success"))
    avg_composite = sum(r["score"].get("composite_score", 0.0) for r in results) / len(results) if results else 0.0
    
    typer.echo(f"Success Rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
    typer.echo(f"Average Composite Score: {avg_composite:.3f}")
    typer.echo(f"\nResults saved to: {run_dir}")
    typer.echo(f"Aggregate: {aggregate_path}")
    typer.echo("")
    typer.echo("💡 Generate detailed report with: vei-report --root " + str(run_dir))


@app.command(name="list")
def list_frontier_scenarios() -> None:
    """List all available frontier scenarios."""
    scenarios = list_scenarios()
    frontier_scenarios = {k: v for k, v in scenarios.items() if k.startswith("f")}
    
    typer.echo("🎯 Frontier Evaluation Scenarios")
    typer.echo("=" * 70)
    
    for name, scenario in sorted(frontier_scenarios.items()):
        metadata = getattr(scenario, "metadata", {})
        difficulty = metadata.get("difficulty", "unknown")
        expected_steps = metadata.get("expected_steps", [0, 0])
        
        typer.echo(f"\n{name}")
        typer.echo(f"  Difficulty: {difficulty}")
        typer.echo(f"  Expected steps: {expected_steps[0]}-{expected_steps[1]}")
        
        if metadata.get("rubric"):
            typer.echo(f"  Rubric dimensions: {', '.join(metadata['rubric'].keys())}")
    
    typer.echo("\n" + "=" * 70)
    typer.echo(f"\nTotal frontier scenarios: {len(frontier_scenarios)}")
    typer.echo(f"\nScenario sets available:")
    for set_name, scenarios_list in FRONTIER_SCENARIO_SETS.items():
        typer.echo(f"  - {set_name}: {len(scenarios_list)} scenarios")


@app.command(name="score")
def score_existing_run(
    artifacts_dir: Path = typer.Option(..., help="Directory containing trace.jsonl"),
    use_llm_judge: bool = typer.Option(False, help="Use LLM-as-judge for quality scoring"),
    output: Optional[Path] = typer.Option(None, help="Output path for score JSON"),
) -> None:
    """Score an existing run with frontier scoring system."""
    
    if not artifacts_dir.exists():
        typer.echo(f"❌ Directory not found: {artifacts_dir}", err=True)
        raise typer.Exit(1)
    
    trace_path = artifacts_dir / "trace.jsonl"
    if not trace_path.exists():
        typer.echo(f"❌ No trace.jsonl found in {artifacts_dir}", err=True)
        raise typer.Exit(1)
    
    typer.echo(f"📊 Computing frontier score for: {artifacts_dir}")
    
    try:
        score = compute_frontier_score(artifacts_dir, use_llm_judge=use_llm_judge)
        
        # Save or print
        if output:
            with open(output, "w") as f:
                json.dump(score, f, indent=2)
            typer.echo(f"✅ Score saved to: {output}")
        else:
            typer.echo(json.dumps(score, indent=2))
    
    except Exception as e:
        typer.echo(f"❌ Scoring failed: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
