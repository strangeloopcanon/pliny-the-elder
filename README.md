## VEI (Virtual Enterprise Internet)

Fully synthetic, MCP-native Slack/Mail/Browser world. A single MCP server exposes tools and a seeded event bus so agents can practice multi-app workflows deterministically and reproducibly.

<!-- Demo branch change for GitHub workflow demonstration -->

### Highlights
- **MCP-native tools**: `slack.*`, `mail.*`, `browser.*`, and `vei.*` helpers.
- **Deterministic**: seeded event bus for replies/arrivals/interrupts; identical runs for a fixed seed + artifacts.
- **No external SaaS**: all data is synthetic; live modes can be sandboxed.

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

## Quickstart

### Prerequisites
- Python 3.11+
- OpenAI API key with access to `gpt-5`

### Install
```bash
pip install -e ".[llm,browser]"
```

### Configure
Create a `.env` at the repo root:
```env
# Required
OPENAI_API_KEY=sk-your-actual-api-key-here

# Optional
# OPENAI_BASE_URL=https://api.openai.com/v1

# VEI configuration
VEI_SSE_URL=http://127.0.0.1:3001/sse
VEI_SEED=42042
VEI_ARTIFACTS_DIR=./_vei_out
```

### Verify setup
```bash
python test_vei_setup.py
```
You should see “All critical checks passed!”. The SSE server may show as “Not running”; it auto-starts when you run a demo.

### Run the demo
- Option A: Demo script
```bash
python run_vei_gpt5_demo.py
```

- Option B: VEI CLI tools
```bash
# Interactive chat
vei-chat --model gpt-5 --max-steps 15

# Automated test
vei-llm-test --model gpt-5 \
  --task "Research product price, get Slack approval < $3200, email vendor for a quote."

# One-command demo with artifacts
vei-demo --mode llm --model gpt-5 --artifacts-dir ./_vei_out/demo_run
```

- Option C: Agents SDK
```bash
python examples/agents_gpt5_vei_sse.py
python examples/agents_gpt5_vei_stdio.py
```

### Start the MCP server (manual, optional)
```bash
VEI_SEED=42042 python -m vei.router.sse
```
SSE endpoints (FastMCP defaults):
- Stream: `http://127.0.0.1:3001/sse`
- Messages: `http://127.0.0.1:3001/messages/`

### LLM-friendly loop
- Call `vei.observe` to get `{time_ms, focus, summary, action_menu, pending_events}`.
- Choose one tool from `action_menu` (or any allowed tool) and call it.
- Repeat; optionally `vei.reset` to restart the episode.

Examples (MCP):
- `vei.act_and_observe {"tool":"browser.read","args":{}}`
- `vei.tick {"dt_ms":15000}`
- `slack.send_message {"channel":"#procurement","text":"Posting summary for approval"}`
- `mail.compose {"to":"sales@macrocompute.example","subj":"Quote request","body_text":"Please send latest price and ETA."}`

### RL environment

Install optional extra and run the example:
```bash
pip install -e .[rl]
python examples/rl_env.py
```

### Examples

```bash
python examples/mcp_client_min.py       # minimal MCP client hitting SSE
python examples/local_router_min.py     # in-process Router loop
python examples/rl_env.py               # RL wrapper minimal run
```

## Configuration
- **MCP server**: `VEI_HOST`, `VEI_PORT` (defaults `127.0.0.1`, `3001`).
- **SSE URL**: `VEI_SSE_URL` (default `http://127.0.0.1:3001/sse`).
- **Artifacts**: `VEI_ARTIFACTS_DIR=/abs/out` writes `trace.jsonl`.
- **Streaming**: `VEI_TRACE_POST_URL=https://collector.example/trace` streams entries (best-effort POST).
- **Scenarios**: `VEI_SCENARIO_NAME`, or `VEI_SCENARIO_FILE=/abs/scenario.json`, or `VEI_SCENARIO_JSON='{"budget_cap_usd":3200,...}'`.
- **OpenAI-compatible routing**: `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`.
- **CLI overrides**: `--openai-base-url`, `--openai-api-key`.
- **Autostart**: set `VEI_DISABLE_AUTOSTART=1` to prevent background SSE startup.

## MCP tools
- `slack.*`: `list_channels`, `open_channel`, `send_message`, `react`, `fetch_thread`.
- `mail.*`: `list`, `open`, `compose`, `reply`.
- `browser.*`: `open`, `find`, `click`, `type`, `submit`, `read`, `back`.
- `vei.*` helpers: `observe`, `act_and_observe`, `tick`, `pending`, `reset`.

## Deterministic replay
- Fixed seed + fixed artifacts + fixed build ⇒ identical tool payloads, event timings, DOM hashes, and screenshots.
- Two layers:
  - Tools replay via `.mcpz` bundles (tool calls, responses, timings).
  - Browser replay via `.wacz` web archives and a DOM-graph (state = node, edge = affordance alias).

## Logging and evaluation

### Artifacts directory
After each run, check the artifacts directory:
```
_vei_out/run_TIMESTAMP/
├── transcript.json     # Full conversation log
├── transcript.jsonl    # Line-by-line events
└── trace.jsonl         # Detailed execution trace
```

### Scoring
```bash
vei-score --artifacts-dir ./_vei_out/run_20240115_143022
```
Evaluates task completion, subgoals, costs (action count), provenance, and constraint compliance.

## Scenarios
- Built-in names (set `VEI_SCENARIO_NAME`):
  - `macrocompute_default` — minimal world (home → pdp → specs).
  - `extended_store` — adds a category page with two products.
- Provide your own via `VEI_SCENARIO_FILE` or `VEI_SCENARIO_JSON`.

### Advanced usage
- Custom scenarios via env/file:
```bash
export VEI_SCENARIO_JSON='{"budget_cap_usd": 5000, "products": [...]}'
export VEI_SCENARIO_FILE=/path/to/scenario.json
```
- Deterministic runs:
```bash
export VEI_SEED=12345
vei-demo --mode llm --artifacts-dir ./run1
export VEI_SEED=12345
vei-demo --mode llm --artifacts-dir ./run2
# diff run1/transcript.json run2/transcript.json
```
- Stream traces:
```bash
export VEI_TRACE_POST_URL=https://your-collector.com/endpoint
```

### Best practices
- Start simple → then scale to complex workflows
- Always set `VEI_ARTIFACTS_DIR`/`--artifacts-dir` for debugging
- Use `vei-score` to validate completion
- Fix the seed for reproducibility
- Monitor `transcript.jsonl` for real-time events

## Test plan (must pass)
- Replay determinism across runs (same seed).
- Event determinism for Slack/Mail.
- Invalid action handling is deterministic.
- Scoring robust to common email quoting/casing variations.

## Safety & compliance
- No external PII; all fixtures synthetic.
- Live browser respects domain whitelist and blocks POST.
- Slack live is for dev workspaces only; rate-limited.

## MCP config snippet
`mcp.json` is included:
```json
{
  "servers": {
    "vei": {
      "command": "python3",
      "args": ["-m", "vei.router"],
      "env": { "VEI_SEED": "42042" }
    }
  }
}
```

## Status
Minimal runnable slice with deterministic Slack/Mail events and a simple virtual site. Extend scenarios under `vei/world/`.
