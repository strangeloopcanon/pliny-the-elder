## VEI (Virtual Enterprise Internet)

Fully synthetic, MCP-native Slack/Mail/Browser world. A single MCP server exposes tools and a seeded event bus so agents can practice multi-app workflows deterministically and reproducibly.

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

### Install (Python 3.11+)
```bash
pip install -e .
```

### Start the MCP server (SSE)
```bash
VEI_SEED=42042 python -m vei.router.sse
```
SSE endpoints (FastMCP defaults):
- Stream: `http://127.0.0.1:3001/sse`
- Messages: `http://127.0.0.1:3001/messages/`

Zero-config: the `vei-llm-test` and `vei-chat` CLIs auto-start a local SSE server if not running (disable with `--no-autostart`).

### LLM-friendly loop
- Call `vei.observe` to get `{time_ms, focus, summary, action_menu, pending_events}`.
- Choose one tool from `action_menu` (or any allowed tool) and call it.
- Repeat; optionally `vei.reset` to restart the episode.

Examples (MCP):
- `vei.act_and_observe {"tool":"browser.read","args":{}}`
- `vei.tick {"dt_ms":15000}`
- `slack.send_message {"channel":"#procurement","text":"Posting summary for approval"}`
- `mail.compose {"to":"sales@macrocompute.example","subj":"Quote request","body_text":"Please send latest price and ETA."}`

### CLI (optional)
```bash
vei-run --seed 42042
# then type tool lines like:
# browser.read {}
# slack.send_message {"channel":"#procurement","text":"Posting summary for approval"}
# mail.compose {"to":"sales@macrocompute.example","subj":"Quote request","body_text":"Please send latest price and ETA."}
```

### LLM smoke test (uses `.env` `OPENAI_API_KEY`)
Recommended:
```bash
VEI_SSE_URL=http://127.0.0.1:3001/sse \
  vei-llm-test --model gpt-5 \
  --task "Research product price, get Slack approval < $3200, email vendor for a quote." > transcript.json
```
Manual server:
```bash
VEI_SEED=42042 python -m vei.router.sse &
VEI_SSE_URL=http://127.0.0.1:3001/sse vei-llm-test --model gpt-5 > transcript.json
```

### Playground
```bash
pip install -e .
VEI_SSE_URL=http://127.0.0.1:3001/sse \
  vei-chat --model gpt-5 --max-steps 12 \
  --task "Summarize specs, request approval, email vendor." > transcript.json
```

### One-command demo

Scripted (no API key):
```bash
vei-demo --mode scripted --artifacts-dir /abs/out
vei-score --artifacts-dir /abs/out
```

LLM (requires `OPENAI_API_KEY`):
```bash
vei-demo --mode llm --model gpt-5 --artifacts-dir /abs/out
```

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

See `.env.example` for a starter template.

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

## Artifacts and scoring
- Set `VEI_ARTIFACTS_DIR` or pass `--artifacts-dir` to write `trace.jsonl`.
- Score a run:
```bash
vei-score --artifacts-dir /abs/path/out
# or stricter success requiring all subgoals:
vei-score --artifacts-dir /abs/path/out --success-mode full
```
Score object captures terminal success, subgoals, costs, provenance, and artifact hashes.

## Scenarios
- Built-in names (set `VEI_SCENARIO_NAME`):
  - `macrocompute_default` — minimal world (home → pdp → specs).
  - `extended_store` — adds a category page with two products.
- Provide your own via `VEI_SCENARIO_FILE` or `VEI_SCENARIO_JSON`.

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
