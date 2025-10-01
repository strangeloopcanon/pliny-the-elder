"""CLI for generating comprehensive evaluation reports and leaderboards.

Usage:
    vei-report --root _vei_out/frontier_eval --format markdown
    vei-report --root _vei_out/frontier_eval --format csv --output results.csv
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from vei.score_frontier import compute_frontier_score

app = typer.Typer(name="vei-report", help="Generate evaluation reports and leaderboards")


def load_all_results(root_dir: Path) -> List[Dict[str, Any]]:
    """Recursively load all frontier_score.json and score.json files."""
    results = []
    
    # Look for aggregate_results.json first (batch runs)
    for aggregate_file in root_dir.rglob("aggregate_results.json"):
        try:
            with open(aggregate_file, "r") as f:
                batch = json.load(f)
                for item in batch:
                    results.append(item)
        except Exception:
            continue
    
    # Also look for individual score files
    for score_file in root_dir.rglob("frontier_score.json"):
        try:
            with open(score_file, "r") as f:
                score = json.load(f)
                
                # Infer metadata from path
                parts = score_file.parts
                scenario = "unknown"
                model = "unknown"
                
                # Try to extract from path structure
                for i, part in enumerate(parts):
                    if part.startswith("f") and "_" in part:
                        scenario = part
                    if i > 0 and "_" in parts[i-1]:
                        model = parts[i-1]
                
                results.append({
                    "scenario": scenario,
                    "model": model,
                    "provider": "unknown",
                    "score": score,
                })
        except Exception:
            continue
    
    # Also check for legacy score.json
    for score_file in root_dir.rglob("score.json"):
        # Skip if we already have frontier_score.json in same dir
        if (score_file.parent / "frontier_score.json").exists():
            continue
        
        try:
            with open(score_file, "r") as f:
                score = json.load(f)
                
                # Convert legacy format to frontier format
                frontier_score = {
                    "success": score.get("success", False),
                    "composite_score": 1.0 if score.get("success") else 0.0,
                    "dimensions": {
                        "correctness": 1.0 if score.get("subgoals", {}).get("email_parsed") else 0.0,
                        "completeness": sum(score.get("subgoals", {}).values()) / 4.0 if score.get("subgoals") else 0.0,
                        "efficiency": 1.0,
                        "communication_quality": 0.5,
                        "domain_knowledge": 0.5,
                        "safety_alignment": 1.0,
                    },
                    "steps_taken": score.get("costs", {}).get("actions", 0),
                    "time_elapsed_ms": score.get("costs", {}).get("time_ms", 0),
                    "legacy": True,
                }
                
                parts = score_file.parts
                scenario = "unknown"
                model = "unknown"
                
                for part in parts:
                    if "macrocompute" in part or part.startswith("p"):
                        scenario = part
                    if any(x in part for x in ["gpt", "claude", "gemini", "grok"]):
                        model = part
                
                results.append({
                    "scenario": scenario,
                    "model": model,
                    "provider": "unknown",
                    "score": frontier_score,
                })
        except Exception:
            continue
    
    return results


def generate_csv_report(results: List[Dict], output_path: Path) -> None:
    """Generate CSV report with all results."""
    
    rows = []
    for r in results:
        score = r["score"]
        dims = score.get("dimensions", {})
        
        row = {
            "model": r["model"],
            "provider": r.get("provider", "unknown"),
            "scenario": r["scenario"],
            "success": score.get("success", False),
            "composite_score": score.get("composite_score", 0.0),
            "correctness": dims.get("correctness", 0.0),
            "completeness": dims.get("completeness", 0.0),
            "efficiency": dims.get("efficiency", 0.0),
            "communication_quality": dims.get("communication_quality", 0.0),
            "domain_knowledge": dims.get("domain_knowledge", 0.0),
            "safety_alignment": dims.get("safety_alignment", 0.0),
            "steps_taken": score.get("steps_taken", 0),
            "time_ms": score.get("time_elapsed_ms", 0),
            "difficulty": score.get("scenario_difficulty", "unknown"),
        }
        rows.append(row)
    
    if not rows:
        return
    
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def generate_markdown_leaderboard(results: List[Dict]) -> str:
    """Generate markdown leaderboard."""
    
    if not results:
        return "No results to display."
    
    # Group by model
    by_model = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)
    
    # Calculate aggregate stats per model
    model_stats = []
    for model, model_results in by_model.items():
        scores = [r["score"] for r in model_results]
        
        success_count = sum(1 for s in scores if s.get("success"))
        success_rate = success_count / len(scores) if scores else 0.0
        avg_composite = sum(s.get("composite_score", 0.0) for s in scores) / len(scores) if scores else 0.0
        avg_steps = sum(s.get("steps_taken", 0) for s in scores) / len(scores) if scores else 0.0
        
        # Aggregate dimension scores
        dims = defaultdict(list)
        for s in scores:
            for k, v in s.get("dimensions", {}).items():
                dims[k].append(v)
        avg_dims = {k: sum(v)/len(v) if v else 0.0 for k, v in dims.items()}
        
        model_stats.append({
            "model": model,
            "provider": model_results[0].get("provider", "unknown"),
            "scenarios_run": len(scores),
            "success_count": success_count,
            "success_rate": success_rate,
            "avg_composite": avg_composite,
            "avg_steps": avg_steps,
            "avg_dims": avg_dims,
        })
    
    # Sort by success rate, then composite score
    model_stats.sort(key=lambda x: (x["success_rate"], x["avg_composite"]), reverse=True)
    
    # Build markdown
    lines = [
        "# 🏆 Frontier Model Evaluation Leaderboard",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total Evaluations:** {len(results)}",
        f"**Models Tested:** {len(model_stats)}",
        "",
        "---",
        "",
        "## Overall Rankings",
        "",
        "| Rank | Model | Provider | Success Rate | Avg Score | Scenarios | Avg Steps |",
        "|------|-------|----------|--------------|-----------|-----------|-----------|",
    ]
    
    for idx, stat in enumerate(model_stats, 1):
        rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}")
        success_pct = f"{stat['success_rate']*100:.1f}%"
        success_icon = "✅" if stat['success_rate'] >= 0.7 else "⚠️" if stat['success_rate'] >= 0.3 else "❌"
        
        lines.append(
            f"| {rank_emoji} | **{stat['model']}** | {stat['provider']} | {success_icon} {success_pct} | "
            f"{stat['avg_composite']:.3f} | {stat['scenarios_run']} | {stat['avg_steps']:.1f} |"
        )
    
    lines.extend(["", "---", "", "## Dimension Breakdown", ""])
    
    # Dimension table
    lines.append("| Model | Correctness | Completeness | Efficiency | Communication | Domain | Safety |")
    lines.append("|-------|-------------|--------------|------------|---------------|--------|--------|")
    
    for stat in model_stats:
        dims = stat['avg_dims']
        lines.append(
            f"| {stat['model']} | {dims.get('correctness', 0):.2f} | {dims.get('completeness', 0):.2f} | "
            f"{dims.get('efficiency', 0):.2f} | {dims.get('communication_quality', 0):.2f} | "
            f"{dims.get('domain_knowledge', 0):.2f} | {dims.get('safety_alignment', 0):.2f} |"
        )
    
    lines.extend(["", "---", "", "## Detailed Results by Scenario", ""])
    
    # Group by scenario
    by_scenario = defaultdict(list)
    for r in results:
        by_scenario[r["scenario"]].append(r)
    
    for scenario, scenario_results in sorted(by_scenario.items()):
        lines.append(f"### {scenario}")
        lines.append("")
        lines.append("| Model | Success | Score | Steps | Dimensions |")
        lines.append("|-------|---------|-------|-------|------------|")
        
        for r in sorted(scenario_results, key=lambda x: x["score"].get("composite_score", 0), reverse=True):
            score = r["score"]
            success_icon = "✅" if score.get("success") else "❌"
            composite = score.get("composite_score", 0.0)
            steps = score.get("steps_taken", 0)
            
            # Top 3 dimensions
            dims = score.get("dimensions", {})
            top_dims = sorted(dims.items(), key=lambda x: x[1], reverse=True)[:3]
            dims_str = ", ".join([f"{k[:3]}:{v:.2f}" for k, v in top_dims])
            
            lines.append(
                f"| {r['model']} | {success_icon} | {composite:.3f} | {steps} | {dims_str} |"
            )
        
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## Insights & Recommendations",
        "",
        f"### Best Overall: {model_stats[0]['model']}" if model_stats else "",
        f"- Success rate: {model_stats[0]['success_rate']*100:.1f}%" if model_stats else "",
        f"- Average composite score: {model_stats[0]['avg_composite']:.3f}" if model_stats else "",
        f"- Average steps: {model_stats[0]['avg_steps']:.1f}" if model_stats else "",
        "",
        "### Performance Trends",
    ])
    
    # Identify strengths/weaknesses
    if model_stats:
        best_model = model_stats[0]
        dims = best_model['avg_dims']
        sorted_dims = sorted(dims.items(), key=lambda x: x[1], reverse=True)
        
        lines.append(f"**{best_model['model']} strengths:**")
        for dim, score in sorted_dims[:2]:
            lines.append(f"- {dim}: {score:.3f}")
        
        lines.append("")
        lines.append(f"**Areas for improvement:**")
        for dim, score in sorted_dims[-2:]:
            lines.append(f"- {dim}: {score:.3f}")
    
    return "\n".join(lines)


@app.command(name="generate")
def generate_report(
    root: Path = typer.Option(..., help="Root directory containing evaluation results"),
    format: str = typer.Option("markdown", help="Output format: markdown, csv, json"),
    output: Optional[Path] = typer.Option(None, help="Output file path (defaults to stdout for markdown)"),
    include_legacy: bool = typer.Option(True, help="Include legacy score.json files"),
) -> None:
    """Generate comprehensive evaluation report from results directory."""
    
    if not root.exists():
        typer.echo(f"❌ Directory not found: {root}", err=True)
        raise typer.Exit(1)
    
    typer.echo(f"📊 Loading results from: {root}")
    
    results = load_all_results(root)
    
    if not results:
        typer.echo("⚠️  No results found", err=True)
        raise typer.Exit(1)
    
    typer.echo(f"✅ Loaded {len(results)} evaluation results")
    
    if format == "csv":
        output_path = output or (root / "leaderboard.csv")
        generate_csv_report(results, output_path)
        typer.echo(f"✅ CSV report saved to: {output_path}")
    
    elif format == "json":
        output_path = output or (root / "leaderboard.json")
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        typer.echo(f"✅ JSON report saved to: {output_path}")
    
    elif format == "markdown":
        markdown = generate_markdown_leaderboard(results)
        
        if output:
            with open(output, "w") as f:
                f.write(markdown)
            typer.echo(f"✅ Markdown report saved to: {output}")
        else:
            typer.echo(markdown)
    
    else:
        typer.echo(f"❌ Unknown format: {format}", err=True)
        typer.echo("Supported formats: markdown, csv, json", err=True)
        raise typer.Exit(1)


@app.command(name="compare")
def compare_models(
    root: Path = typer.Option(..., help="Root directory containing evaluation results"),
    models: str = typer.Option(..., help="Comma-separated list of models to compare"),
    scenario: Optional[str] = typer.Option(None, help="Filter by specific scenario"),
) -> None:
    """Compare specific models head-to-head."""
    
    results = load_all_results(root)
    
    if not results:
        typer.echo("⚠️  No results found", err=True)
        raise typer.Exit(1)
    
    model_list = [m.strip() for m in models.split(",")]
    
    # Filter results
    filtered = [r for r in results if r["model"] in model_list]
    if scenario:
        filtered = [r for r in filtered if r["scenario"] == scenario]
    
    if not filtered:
        typer.echo(f"⚠️  No results found for models: {models}", err=True)
        raise typer.Exit(1)
    
    # Group by model
    by_model = defaultdict(list)
    for r in filtered:
        by_model[r["model"]].append(r)
    
    # Print comparison
    typer.echo("=" * 80)
    typer.echo(f"🔬 Model Comparison: {', '.join(model_list)}")
    if scenario:
        typer.echo(f"   Scenario: {scenario}")
    typer.echo("=" * 80)
    typer.echo("")
    
    for model in model_list:
        model_results = by_model.get(model, [])
        
        if not model_results:
            typer.echo(f"{model}: No results")
            continue
        
        scores = [r["score"] for r in model_results]
        success_rate = sum(1 for s in scores if s.get("success")) / len(scores)
        avg_composite = sum(s.get("composite_score", 0.0) for s in scores) / len(scores)
        avg_steps = sum(s.get("steps_taken", 0) for s in scores) / len(scores)
        
        typer.echo(f"{'='*80}")
        typer.echo(f"Model: {model}")
        typer.echo(f"  Scenarios: {len(scores)}")
        typer.echo(f"  Success Rate: {success_rate*100:.1f}%")
        typer.echo(f"  Avg Composite Score: {avg_composite:.3f}")
        typer.echo(f"  Avg Steps: {avg_steps:.1f}")
        
        # Dimension averages
        dims = defaultdict(list)
        for s in scores:
            for k, v in s.get("dimensions", {}).items():
                dims[k].append(v)
        
        typer.echo("  Dimensions:")
        for dim, values in sorted(dims.items()):
            avg = sum(values) / len(values) if values else 0.0
            typer.echo(f"    - {dim}: {avg:.3f}")
        
        typer.echo("")


@app.command(name="summary")
def quick_summary(
    root: Path = typer.Option(..., help="Root directory containing evaluation results"),
) -> None:
    """Print a quick summary of evaluation results."""
    
    results = load_all_results(root)
    
    if not results:
        typer.echo("⚠️  No results found", err=True)
        raise typer.Exit(1)
    
    # Overall stats
    success_count = sum(1 for r in results if r["score"].get("success"))
    success_rate = success_count / len(results)
    avg_composite = sum(r["score"].get("composite_score", 0.0) for r in results) / len(results)
    
    # By model
    by_model = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)
    
    # By scenario
    by_scenario = defaultdict(list)
    for r in results:
        by_scenario[r["scenario"]].append(r)
    
    typer.echo("=" * 70)
    typer.echo("📊 Evaluation Summary")
    typer.echo("=" * 70)
    typer.echo(f"Total Evaluations: {len(results)}")
    typer.echo(f"Success Rate: {success_rate*100:.1f}% ({success_count}/{len(results)})")
    typer.echo(f"Avg Composite Score: {avg_composite:.3f}")
    typer.echo("")
    typer.echo(f"Models Tested: {len(by_model)}")
    for model, model_results in sorted(by_model.items(), key=lambda x: len(x[1]), reverse=True):
        model_success = sum(1 for r in model_results if r["score"].get("success"))
        typer.echo(f"  - {model}: {len(model_results)} scenarios ({model_success} successes)")
    
    typer.echo("")
    typer.echo(f"Scenarios Tested: {len(by_scenario)}")
    for scenario, scenario_results in sorted(by_scenario.items()):
        scenario_success = sum(1 for r in scenario_results if r["score"].get("success"))
        typer.echo(f"  - {scenario}: {len(scenario_results)} runs ({scenario_success} successes)")
    
    typer.echo("=" * 70)


if __name__ == "__main__":
    app()
