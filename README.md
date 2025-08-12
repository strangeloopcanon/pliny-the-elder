VEI (Virtual Enterprise Internet)

Fully synthetic, MCP-native Slack/Mail/Browser world. One MCP server exposes tools:

- slack.*: list_channels, open_channel, send_message, react, fetch_thread
- mail.*: list, open, compose, reply
- browser.*: open, find, click, type, submit, read, back
- vei.*: observe, reset (LLM-friendly helpers)

Deterministic via seeded event bus. No external SaaS.

Quickstart

1) Install (Python 3.11+)

```bash
pip install -e .
```

2) Start the MCP server (SSE recommended)

```bash
VEI_SEED=42042 python -m vei.router.sse
```

SSE endpoints (FastMCP defaults):
- Stream: `http://127.0.0.1:3001/sse`
- Messages: `http://127.0.0.1:3001/messages/`
Any MCP client can connect. A stdio entry also exists (`python -m vei.router`) but SSE is more robust for automated clients/tests.

Zero-config option: the `vei-llm-test` and `vei-chat` CLIs will auto-start a local SSE server if it is not already running. You can disable this behavior with `--no-autostart`.

3) LLM-friendly use

- Minimal loop for an agent:
  1) Call `vei.observe` to get a compact observation with `action_menu`.
  2) Pick a tool from `action_menu` (or any allowed tool) and call it once.
  3) Repeat `vei.observe` → tool call.
  4) Optionally call `vei.reset` to reset the episode (seeded).

- Example tool calls an LLM can issue (MCP):

  - `vei.observe {}` → returns `{time_ms, focus, summary, action_menu, pending_events}`
  - `vei.act_and_observe {"tool":"browser.read","args":{}}` → returns `{result, observation}` (one-step convenience)
  - `vei.tick {"dt_ms": 15000}` → advance time deterministically and deliver due events
  - `vei.pending {}` → returns pending event counts without advancing time
  - `browser.read {}`
  - `slack.send_message {"channel":"#procurement","text":"Posting summary for approval"}`
  - `mail.compose {"to":"sales@macrocompute.example","subj":"Quote request","body_text":"Please send latest price and ETA."}`
  - `vei.reset {"seed":42042}` (optional)

MCP config

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

CLI (optional)

```bash
vei-run --seed 42042
# then type tool lines like:
# browser.read {}
# slack.send_message {"channel":"#procurement","text":"Posting summary for approval"}
# mail.compose {"to":"sales@macrocompute.example","subj":"Quote request","body_text":"Please send latest price and ETA."}
```

LLM smoke test (uses .env OPENAI_API_KEY)

Recommended (auto-starts server if needed):
```bash
VEI_SSE_URL=http://127.0.0.1:3001/sse vei-llm-test --model gpt-5 --task "Research product price, get Slack approval < $3200, email vendor for a quote." > transcript.json
```

Alternatively (manual server):
```bash
VEI_SEED=42042 python -m vei.router.sse &
VEI_SSE_URL=http://127.0.0.1:3001/sse vei-llm-test --model gpt-5 > transcript.json
```

The CLI connects to the MCP SSE server and has the LLM follow the observe → plan → act loop via MCP tools using your chosen model.

Playground (interactive GPT-5 loop)

```bash
pip install -e .
VEI_SSE_URL=http://127.0.0.1:3001/sse vei-chat --model gpt-5 --max-steps 12 --task "Summarize specs, request approval, email vendor." > transcript.json
```

Tips
- Use `vei.help {}` and `vei.ping {}` from any MCP client to discover tools and confirm health.
- Set `VEI_ARTIFACTS_DIR=/abs/out` before starting the server to produce a `trace.jsonl`; then `vei-score --artifacts-dir /abs/out`.

Server autostart
- Importing this package starts an SSE server in the background by default (sitecustomize) to make local use frictionless.
- Opt out by setting `VEI_DISABLE_AUTOSTART=1` if you embed VEI in a larger app or test harness and want explicit control.
 - The `vei-llm-test` and `vei-chat` CLIs also auto-start the SSE server if it is not detected on `VEI_SSE_URL` (use `--no-autostart` to disable).

Configuration (succinct)
- MCP server host/port: `VEI_HOST`, `VEI_PORT` (defaults `127.0.0.1`, `3001`).
- MCP SSE URL for clients: `VEI_SSE_URL` (default `http://127.0.0.1:3001/sse`).
- Trace output dir: `VEI_ARTIFACTS_DIR=/abs/out` writes `trace.jsonl`.
- Trace streaming: optional `VEI_TRACE_POST_URL=https://collector.example/trace` streams each entry as JSON via POST.
- OpenAI SDK routing: `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` for OpenAI-compatible gateways.
- CLI overrides: `vei-llm-test` and `vei-chat` accept `--openai-base-url` and `--openai-api-key`.
- Scenario config (optional): set `VEI_SCENARIO_FILE=/abs/scenario.json` or `VEI_SCENARIO_JSON='{"budget_cap_usd":3200,...}'` to customize Slack/Mail/Browser world.

Exact LLM call sites
- `vei/cli/vei_llm_test.py` at the call to `client.chat.completions.create(...)`.
- `vei/cli/_llm_loop.py` at the call to `client.chat.completions.create(...)`.

Exact MCP endpoints
- Server created in `vei/router/server_fastmcp.py` with FastMCP defaults (`/sse`, `/messages/`).
- SSE runner in `vei/router/sse.py` uses those defaults and runs `server.run("sse")`.

Routing models to your environment
- Set `OPENAI_BASE_URL=https://your-openai-compatible-gateway/v1` and `OPENAI_API_KEY=...`.
- Or pass via CLI: `vei-llm-test --openai-base-url ... --openai-api-key ...`.

Passing a task to the LLM
- Both CLIs accept `--task "..."`. This adds a preface message like `Task: ...` so the model sequences MCP actions toward your goal.

Examples:
```bash
vei-llm-test --model gpt-5 --task "Read product page, post Slack approval summary, email vendor, wait for reply."
vei-chat --model gpt-5 --task "Under $3200, get approval with citations and parse the vendor's ETA." --max-steps 12
```

Telemetry
- Persistent file: set `VEI_ARTIFACTS_DIR` to store `trace.jsonl`.
- Streaming: set `VEI_TRACE_POST_URL` to POST each entry (best-effort, non-blocking).

Artifacts and scoring

- Set `VEI_ARTIFACTS_DIR` or pass `--artifacts-dir` to write a `trace.jsonl`.
- Score a run:

```bash
vei-score --artifacts-dir /abs/path/out
# or stricter success requiring all subgoals:
vei-score --artifacts-dir /abs/path/out --success-mode full
```

Config and Notes

- Determinism: LCG RNG + logical bus clock; set `VEI_SEED` for reproducibility.
- Slack approval policy env: `VEI_BUDGET_CAP` (default 3500), derail rate `VEI_SLACK_DERAIL_PCT` (default 0.1).
- SSE URL override for tools/tests: `VEI_SSE_URL` (default `http://127.0.0.1:3001/sse`).
- Safety: all data is synthetic; no external services are contacted.
- Autostart: set `VEI_DISABLE_AUTOSTART=1` to prevent background SSE startup.

Scenarios catalog
- Built-in names (set `VEI_SCENARIO_NAME`):
  - `macrocompute_default` — default minimal world (home → pdp → specs), standard Slack/Mail behavior.
  - `extended_store` — adds a category page with two products (pdp1, pdp2) and deeper browser navigation.
- Alternatively, provide your own scenario via:
  - `VEI_SCENARIO_FILE=/abs/scenario.json` (see `vei-build-scenario` for a template), or
  - `VEI_SCENARIO_JSON='{"budget_cap_usd":3200,...}'`.


Status

Minimal runnable slice with deterministic Slack/Mail events and a simple virtual site. Extend scenarios under `vei/world/`.
