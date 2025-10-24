## VEI (Virtual Enterprise Internet)

![VEI Virtual Office](docs/assets/virtual_office.gif)
<p align="center"><sub>Conceptual office view</sub></p>

Fully synthetic, MCP-native Slack/Mail/Browser world. A single MCP server exposes tools and a seeded event bus so agents can practice multi-app workflows deterministically and reproducibly.

<!-- Demo branch change for GitHub workflow demonstration -->

### Highlights
- **MCP-native tools**: `slack.*`, `mail.*`, `browser.*`, and `vei.*` helpers (now including `vei.tools.search` for catalog retrieval).
- **Deterministic**: seeded event bus for replies/arrivals/interrupts; identical runs for a fixed seed + artifacts.
- **No external SaaS**: all data is synthetic; live modes can be sandboxed.

## Run Visualizations

- `vei-visualize replay _vei_out/<run_id>/transcript.json` streams the run step-by-step in your terminal (JSON or JSONL).
- `vei-visualize flow _vei_out/<run_id>/transcript.json --out _vei_out/<run_id>/flow.html` renders an interactive HTML map reusing the shared Slack/Mail/Docs/CRM layout (falls back to `trace.jsonl` if the transcript is empty).
- `vei-visualize dashboard _vei_out/gpt5_llmtest/multi_provider_20251012_122020/multi_channel --step-ms 400 --out _vei_out/.../flow_dashboard.html` bundles every provider into a single selector page.
- `vei-visualize export _vei_out/<run_id>/transcript.json docs/assets/<name>.gif --step-ms 400 --stride 2` captures the same animation for docs/slides (requires `pip install -e ".[browser]" && playwright install`).

| openai/gpt-5 | anthropic/claude-sonnet-4-5 |
| --- | --- |
| ![openai/gpt-5 multi-channel flow](docs/assets/gpt5_flow.gif) | ![claude-sonnet-4-5 multi-channel flow](docs/assets/claude_flow.gif) |

### Table of Contents
1. [Architecture](#architecture)
2. [Evaluation Workflow](#evaluation-workflow)
   - [Baseline Task](#baseline-task)
   - [Latest Multi-Provider Snapshot](#latest-multi-provider-snapshot)
   - [Frontier Scenarios](#frontier-scenarios)
3. [Quickstart](#quickstart)
   - [Install](#install)
   - [Configure](#configure)
   - [Verify Setup](#verify-setup)
   - [Smoke Tests](#smoke-tests)
   - [Run the Demo](#run-the-demo)
   - [Testing](#testing)
4. [Configuration Cheatsheet](#configuration-cheatsheet)
5. [RL Environment & Offline Training](#rl-environment--offline-training)
6. [Appendix](#appendix)
   - [Deterministic Replay](#deterministic-replay)
   - [Artifacts & Scoring](#artifacts--scoring)

### Architecture
```
Agent ──MCP──► VEI Router (this repo)
                      │
                      ├─ slack.{live|replay|sim}
                      ├─ email.{live_local|replay|sim}
                      └─ browser.{replay|live}
                               ▲
                        Seeded Event Bus (async)
                               ▲
                     Replay Stores (.mcpz + .wacz/.har)
```

### Modes (per connector)
- **Live**: dev/sandbox endpoints with guardrails.
- **Replay**: deterministic playback from `.mcpz` and `.wacz`.
- **Sim**: seeded emulators that speak the same MCP schemas.

## Evaluation Workflow

### Baseline Task
- **Objective**: Read the MacroBook product page with citations, post an approval to `#procurement` (budget <$3200), email the vendor for a quote, and parse the reply (price + ETA).  
- **Run it**:
  ```bash
  export VEI_ARTIFACTS_DIR=_vei_out/gpt5_llmtest
  VEI_SEED=42042 vei-llm-test --model gpt-5 --max-steps 32 \
    --task "Open product page, cite specs, post approval under $3200, email sales@macrocompute.example for a quote, wait for the reply."
  vei-score --artifacts-dir _vei_out/gpt5_llmtest --success-mode full
  ```
- **Artifacts**: `trace.jsonl`, `transcript.json`, and `score.json` land in the artifacts directory. The router auto-starts over stdio; no manual server step required.
- **Troubleshooting**: If the run stalls waiting for email replies, advance time with `vei.tick {dt_ms:15000}` or increase `--max-steps`. Missing actions? inspect the transcript and `score.json["policy_findings"]`.

### Latest Multi-Provider Snapshot

Five providers attempted the seeded `VEI_SCENARIO=multi_channel` workflow (`_vei_out/datasets/multi_channel_seed42042.json`, cap 40 tool calls). None cleared every enterprise subgoal; use this as the current regression baseline.

| Model | Success | Actions | Subgoals (cit/appr/appr_amt/email_sent/email_parsed/doc/ticket/crm) | Policy (warn/err) | Warning highlights |
| --- | --- | ---: | --- | --- | --- |
| openai/gpt-5 | ✗ | 39 | 1/1/0/1/0/0/0/0 | 2/0 | Mail repetition; missing doc/ticket updates |
| openai/gpt-5-codex | ✗ | 37 | 1/1/1/1/0/0/0/0 | 2/0 | Browser/Slack loops; no doc/ticket coverage |
| anthropic/claude-sonnet-4-5 | ✗ | 26 | 1/1/0/0/0/0/0/1 | 5/0 | CRM note lacks ETA; Docs/Tickets untouched |
| openrouter/x-ai/grok-4 | ✗ | 10 | 1/1/0/1/0/0/0/0 | 2/0 | Halts early; doc/ticket omissions |
| google/models/gemini-2.5-pro | ✗ | 4 | 1/1/0/1/0/0/0/0 | 2/0 | Bails quickly; no documentation |

Additional reruns:
- `multi_provider_20251012_145901`: Gemini 2.5 Pro reached 23 actions and updated a ticket, but still skipped Docs logging.
- OpenRouter reruns (e.g. `multi_provider_20251011_230810`) fail when Grok emits non-JSON—inspect `stderr.log` for raw payloads.

Regenerate dashboards or CSV summaries:
```bash
python tools/render_multi_provider_dashboard.py _vei_out/gpt5_llmtest > dashboard.md
python tools/render_multi_provider_dashboard.py --latest-only _vei_out/gpt5_llmtest
```

### Frontier Scenarios
The extended `run_multi_provider_eval.sh` suite layers in seven multi-hop enterprise scenarios (budget reconciliation, urgent ambiguity, contradictory requirements, compliance audit, cascading failure recovery, ethical refusals, and data privacy checks). Expect 35–80 steps with multi-system coordination. Full details live in [docs/FRONTIER_EVAL.md](docs/FRONTIER_EVAL.md).

Quick launch:
```bash
./run_multi_provider_eval.sh
VEI_MODELS='gpt-5:openai,claude-sonnet-4-5:anthropic' \
  VEI_SCENARIOS='multi_channel,multi_channel_compliance' ./run_multi_provider_eval.sh
```
Set `VEI_BASELINES=scripted` or `bc:./_vei_out/bc_policy.json` to compare scripted/BC baselines alongside LLM runs.

## Quickstart

### Prerequisites
- Python 3.11+
- LLM API key(s) for demos/tests: OpenAI, Anthropic, Google, or OpenRouter
- Smoke tests and stdio transport do not require a key

### Install
```bash
pip install -e ".[llm,sse]"
```
Optional: add `[browser]` only for live browser automation (Playwright).

### Configure
Create a `.env` at the repo root:
```env
# LLM Providers (add any/all you plan to use)
OPENAI_API_KEY=sk-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
GOOGLE_API_KEY=your-google-api-key-here       # or GEMINI_API_KEY
OPENROUTER_API_KEY=sk-or-your-openrouter-key-here

# Optional
# OPENAI_BASE_URL=https://api.openai.com/v1

# VEI configuration
VEI_SSE_URL=http://127.0.0.1:3001/sse
VEI_SEED=42042
VEI_ARTIFACTS_DIR=./_vei_out
VEI_MONITORS=tool_aware  # Enable heuristic monitor findings in state snapshots
```

### Verify Setup
```bash
python test_vei_setup.py
```
You should see “All critical checks passed!”. The SSE server may show as “Not running”; it auto-starts when you run a demo.

### Smoke Tests
Quick end-to-end checks without an API key:
```bash
# StdIO MCP transport (spawns python -m vei.router)
vei-smoke --transport stdio --timeout-s 30

# SSE MCP transport (auto-starts python -m vei.router.sse if needed)
vei-smoke --transport sse --timeout-s 30

# Or via a Python script that runs both and falls back to a direct Router test
python tests/test_vei_transports.py
```

### Run the Demo
Use the VEI CLI tools
```bash
# Interactive chat (stdio default; SSE optional)
vei-chat --model gpt-5 --max-steps 15 --transport stdio --timeout-s 45
# Or explicitly use SSE (requires local SSE or remote server)
vei-chat --model gpt-5 --max-steps 15 --transport sse --timeout-s 45

# Automated test
vei-llm-test --model gpt-5 \
  --task "Research product price, get Slack approval < $3200, email vendor for a quote."

# Limit the prompt-visible tool catalog (baseline tools stay available).
vei-llm-test --model gpt-5 --tool-top-k 12 \
  --task "Research product price, get Slack approval < $3200, email vendor for a quote."

# One-command demo with artifacts
vei-demo --mode llm --model gpt-5 --artifacts-dir ./_vei_out/demo_run
vei-demo --mode llm --transport stdio --model gpt-5 --artifacts-dir ./_vei_out/demo_run
```

### Dataset tooling & evaluation

Follow the canonical procurement workflow, then adapt it as needed:

1. **Generate a deterministic dataset**
   ```bash
   vei-rollout procurement --episodes 3 --seed 42042 --output ./_vei_out/rollout.json
   ```
2. **Package optional source datasets** (Slack/Mail/Tickets/Docs)
   ```bash
   vei-pack slack --export-path ./slack_export --output ./datasets/slack.json
   vei-pack mail --mail-dir ./mail_messages --output ./datasets/mail.json
   vei-pack tickets --tickets-dir ./ticket_updates --output ./datasets/tickets.json
   vei-pack docs --docs-dir ./docs_snapshot --output ./datasets/docs.json
   ```
3. **Train a behaviour-cloning policy**
   ```bash
   vei-train bc --dataset ./_vei_out/rollout.json --output ./_vei_out/bc_policy.json
   ```
4. **Score scripted or BC policies** (emits `trace.jsonl` + `score.json`)
   ```bash
   vei-eval scripted --seed 42042 --artifacts ./_vei_out/eval_scripted
   vei-eval bc --model ./_vei_out/bc_policy.json --seed 42042 --artifacts ./_vei_out/eval_bc
   ```

To benchmark an LLM against the same dataset:

```bash
vei-llm-test --model gpt-5 --task "Research vendor quote" --dataset ./_vei_out/rollout.json \
  --artifacts ./_vei_out/llm_eval
```

To exercise richer environments (tickets + docs + seeded disruptions):

```bash
export VEI_SCENARIO=multi_channel
vei-llm-test --model gpt-5 \
  --task "Review ticket TCK-42, gather laptop quote, and email results" \
  --max-steps 12 --artifacts ./_vei_out/llm_eval_multichannel

# Compliance variant stresses doc/ticket linking and audit follow-ups
export VEI_SCENARIO=multi_channel_compliance
vei-llm-test --model gpt-5 \
  --task "Capture quote in Docs, update all linked tickets, and satisfy audit reminders" \
  --max-steps 14 --artifacts ./_vei_out/llm_eval_compliance
unset VEI_SCENARIO
```

After each run, review `trace.jsonl` and `score.json` in the chosen `--artifacts` directory to assess behaviour.

### Testing
### Testing
Prefer invoking pytest via the active interpreter to avoid mismatched runtimes:
```bash
python -m pytest -q
```
Live LLM smoke (stdio transport; requires `OPENAI_API_KEY`):
```bash
python -m pytest -q -k llm_stdio_smoke
```
Notes: the suite autostarts the router over stdio, writes `trace.jsonl` under `VEI_ARTIFACTS_DIR`, and honours `VEI_MODEL` / `LLM_SMOKE_PROMPT` overrides.

## Configuration Cheatsheet
- `VEI_ARTIFACTS_DIR` — where traces, transcripts, and scores are saved (set this for every run).
- `VEI_SEED` — fixes event ordering for deterministic replays.
- `VEI_SCENARIO` / `VEI_SCENARIO_CONFIG` — pick or override world templates; `VEI_SCENARIO_RANDOM=1` samples one at random.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY` — provider credentials; override per CLI with `--openai-api-key`/`--openai-base-url`.
- `VEI_DISABLE_AUTOSTART=1` — prevent the CLIs from spawning an SSE server (useful inside existing supervisors).
- Transports: stdio is the default for CLI/tests; add `--transport sse` only when pointing at `python -m vei.router.sse`.

## RL Environment & Offline Training
### Datasets & Behaviour Cloning
```bash
vei-rollout procurement --episodes 5 --seed 42042 --output ./_vei_out/rollout.json
vei-train bc --dataset ./_vei_out/rollout.json --output ./_vei_out/bc_policy.json
vei-eval bc --model ./_vei_out/bc_policy.json --seed 42042 --artifacts ./_vei_out/eval_bc
```
`vei-eval scripted` runs the scripted baseline; `vei-score` consumes the resulting `trace.jsonl` for a quick success/failure check.

### ERP & CRM Twins
- ERP tools: `erp.create_po`, `erp.receive_goods`, `erp.submit_invoice`, `erp.match_three_way`, `erp.post_payment`.
- CRM tools: `crm.create_contact`, `crm.create_company`, `crm.create_deal`, `crm.update_deal_stage`, `crm.log_activity`.
- Alias packs (`--alias-packs xero,netsuite` / `--crm-alias-packs hubspot`) expose vendor-flavoured names. Error rates (`VEI_ERP_ERROR_RATE`, `VEI_CRM_ERROR_RATE`) inject deterministic failures for testing.

### Custom Loops
Many clients simply loop on `vei.observe → {plan} → vei.act_and_observe`. After outbound mail or Slack posts, issue `vei.tick {"dt_ms":15000}` to deliver replies. `vei.state {"tool_tail": 5}` tails recent tool receipts for debugging.

## Appendix
### Deterministic Replay
Fixed seed + fixed artifacts + fixed build ⇒ identical tool payloads, event timings, DOM hashes, and screenshots. Tools replay from `.mcpz` bundles; browser state replays from `.wacz` web archives.

### Artifacts & Scoring
Runs land in `_vei_out/<run_id>/`:
```
├── trace.jsonl     # step-level log used by vei-score
├── transcript.json # human-readable summary
└── score.json      # success/subgoal/policy findings
```
Evaluate with `vei-score --artifacts-dir <dir> [--success-mode full]`. Use `vei-state` to inspect snapshots or receipts when auditing behaviour.
