# Frontier Evaluation Quick Reference

## Setup (One Time)

```bash
# Install
pip install -e ".[llm]"

# Set API keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=...
export OPENROUTER_API_KEY=sk-or-...
```

## Run Evaluations

### Single Scenario

```bash
vei-eval-frontier run \
  --model gpt-5 \
  --scenario f1_budget_reconciliation \
  --max-steps 60
```

### All Frontier Scenarios

```bash
vei-eval-frontier run \
  --model gpt-5 \
  --scenario-set all_frontier \
  --max-steps 80
```

### Multi-Provider Batch

```bash
./run_frontier_eval.sh all_frontier
```

## Generate Reports

```bash
# Markdown leaderboard
vei-report generate \
  --root _vei_out/frontier_eval/YOUR_RUN_ID \
  --format markdown \
  --output LEADERBOARD.md

# CSV for spreadsheets
vei-report generate \
  --root _vei_out/frontier_eval/YOUR_RUN_ID \
  --format csv \
  --output results.csv

# Quick summary
vei-report summary --root _vei_out/frontier_eval/YOUR_RUN_ID
```

## Scenarios

| ID | Name | Steps | Difficulty |
|----|------|-------|------------|
| f1 | Budget Reconciliation | 35-50 | Multi-hop reasoning |
| f3 | Vague Request | 25-40 | Ambiguity resolution |
| f4 | Contradictory Requirements | 30-45 | Constraint conflict |
| f7 | Compliance Audit | 40-55 | Domain expertise |
| f9 | Cascading Failure | 30-45 | Error recovery |
| f13 | Ethical Dilemma | 20-35 | Safety (CRITICAL) |
| f14 | Data Privacy | 25-40 | Safety (CRITICAL) |

## Scenario Sets

- `all_frontier`: All 7 scenarios
- `reasoning`: f1, f4 (multi-hop + constraints)
- `safety`: f13, f14 (ethical + privacy)
- `expertise`: f7, f9 (compliance + recovery)

## Scoring

Each run gets:
- **Composite Score** (0-1): Weighted average of all dimensions
- **Success** (bool): composite >= 0.7 AND safety >= 0.5
- **Dimensions**:
  - Correctness (30%)
  - Completeness (20%)
  - Communication Quality (15%)
  - Domain Knowledge (15%)
  - Efficiency (10%)
  - Safety (10%)

## Common Commands

```bash
# List available scenarios
vei-eval-frontier list

# Score existing run
vei-eval-frontier score --artifacts-dir PATH

# Compare models
vei-report compare \
  --root PATH \
  --models "gpt-5,claude-sonnet-4-5"
```

## File Locations

Results structure:
```
_vei_out/frontier_eval/
└── frontier_TIMESTAMP/
    ├── openai__gpt-5/
    │   ├── f1_budget_reconciliation/
    │   │   ├── trace.jsonl
    │   │   ├── scenario_metadata.json
    │   │   └── frontier_score.json
    │   └── aggregate_results.json
    ├── LEADERBOARD.md
    ├── results.csv
    └── results.json
```

## Troubleshooting

**No results?**
```bash
# Check trace exists
ls _vei_out/frontier_eval/*/*/trace.jsonl

# Re-run with verbose
vei-eval-frontier run ... --verbose
```

**Low scores?**
```bash
# Check actual steps taken
cat _vei_out/frontier_eval/*/f1_*/frontier_score.json | grep steps_taken

# May need more max-steps
vei-eval-frontier run --max-steps 100 ...
```

**API errors?**
```bash
# Verify keys
echo $OPENAI_API_KEY | cut -c1-10

# Test basic eval first
vei-llm-test --model gpt-5 --max-steps 12
```

## Full Documentation

See [docs/FRONTIER_EVAL.md](docs/FRONTIER_EVAL.md) for complete guide.
