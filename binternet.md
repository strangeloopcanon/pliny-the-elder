# Virtual Enterprise Internet (VEI) — v1 Spec (MCP‑native)

## Why this exists (tight)

Goal: give labs a **reproducible, asynchronous, multi‑app world** that looks like a real enterprise stack but is safe to hammer and easy to grade. v1 uses **MCP servers** for three pillars:

* **Slack** (approvals/comms),
* **Email** (request/response chains),
* **Browser** (research & evidence capture).

Design center:

* **One tool interface (MCP)**; backend toggles per service: **Live ↔ Replay ↔ Sim**.
* **Seeded asynchrony** (Slack replies, email arrivals) with **deterministic replays**.
* **Execution‑based scoring** and **signed traces** so results are independently reproducible.

Non‑goals for v1: payments, checkout, returns. Those are v1.5+. Keep v1 lean and bulletproof.

---

# High‑level architecture

```
Agent (any) ──MCP──► VEI Router (this repo)
                      │
                      ├─ slack.{live|replay|sim}  (MCP server contract)
                      ├─ email.{live_local|replay|sim}  (MCP server contract)
                      └─ browser.{replay|live}  (MCP server contract)
                               ▲
                        Seeded Event Bus (async)
                               ▲
                     Replay Stores (.mcpz + .wacz/.har)
```

* **VEI Router**: single MCP server that **mounts** Slack/Email/Browser tools and arbitrates mode & seed.
* **Connectors**: each service implements the **same MCP tool schema** across backends.
* **Event Bus**: one seeded priority queue for all asynchronous events (message replies, email deliveries, timers).
* **Replay Stores**:

  * `.mcpz` — signed sequence of MCP tool calls, responses, and webhooks with timing.
  * `.wacz/.har` — web archives for browser assets + a DOM‑graph for action‑sequence replay.

---

# Modes (per connector)

* **Live**: hit dev/sandbox endpoints or local services with guardrails.
* **Replay**: return recorded responses (and emit recorded webhooks) from `.mcpz`; for browser, serve from `.wacz/.har` and a DOM‑graph. **Deterministic per seed**.
* **Sim**: stateful emulator speaking the *same* MCP tool schema; seeded stochasticity; high throughput.

Example config:

```yaml
tenant: demo-acme
seed: 42042
modes:
  slack: sim          # live (dev workspace) | replay | sim
  email: live_local   # sim | replay | live_local (Mailpit)
  browser: replay     # live (whitelist) | replay
limits:
  slack: { rps: 3, concurrent: 5 }
  email: { rps: 5, concurrent: 5 }
  browser: { rps: 2, concurrent: 3 }
```

---

# MCP tool contracts (v1)

## Slack (namespace: `slack.*`)

**Why**: approvals, clarifications, interruptions; core enterprise glue.

**Tools**

* `slack.list_channels() -> [channel]`
* `slack.open_channel(channel: str) -> {messages, unread_count}`
* `slack.send_message(channel: str, text: str, thread_ts?: str) -> {ts}`
* `slack.react(channel: str, ts: str, emoji: str) -> {ok: bool}`
* `slack.fetch_thread(channel: str, thread_ts: str) -> {messages}`
* `slack.search(query: str) -> {hits}` (optional v1)
* **Events (async):** `slack.message(channel, ts, user, text, thread_ts?)`

**Backends**

* `slack.sim`: seeded personas (e.g., `@cfo`, `@itops`) with reply distributions; templated paraphrases; off‑topic/no‑reply probabilities.
* `slack.replay`: returns recorded messages; schedules recorded events at recorded offsets.
* `slack.live`: optional dev workspace; rate‑limited; no PII; webhook → Event Bus.

## Email (namespace: `mail.*`)

**Why**: external comms, attachments, quote parsing; introduces delays and clutter.

**Tools**

* `mail.list(folder: str="INBOX") -> [{id, from, subj, time, unread}]`
* `mail.open(id: str) -> {headers, body_text, parts[]}`
* `mail.compose(to: str, subj: str, body_text: str, attachments?: [ref]) -> {id}`
* `mail.reply(id: str, body_text: str) -> {id}`
* **Events (async):** `mail.arrival(id, folder)`

**Backends**

* `mail.live_local`: Mailpit/MailHog container (SMTP/IMAP); VEI wraps it as MCP.
* `mail.replay`: deterministic playback of arrivals and opens.
* `mail.sim`: seeded arrival schedules; realistic templates (vendor replies, “OOO”, bounces), MIME parts.

## Browser (namespace: `browser.*`)

**Why**: research, evidence capture, provenance; UI discipline.

**Tools**

* `browser.open(url: str) -> {url, title}`
* `browser.find(query: str, top_k: int=10) -> [{node_id, role, name}]`  *(search visible affordances by role/name/text, not arbitrary CSS)*
* `browser.click(node_id: str) -> {url}`
* `browser.type(node_id: str, text: str) -> {ok: bool}`
* `browser.submit(form_id: str) -> {url}`
* `browser.read() -> {url, title, excerpt: str, axtree?: obj, screenshot_ref: blob}`
* `browser.back() -> {url}`
* **Events (sync to agent step)**: cookie banners/newsletter modals may appear via seeded variants; exposed as `find(...)` affordances.

**Backends**

* `browser.replay`: serves from `.wacz/.har` under a **DOM‑graph** (state = DOM node; edge = affordance alias) so **action sequences are deterministic**.
* `browser.live`: Playwright to whitelisted domains; network guard; robots/TOS respect.

---

# Seeded Event Bus (asynchrony, reproducible)

Deterministic per seed; schedules and dispatches:

* Slack replies (per‑persona lognormal delays; no‑reply/derail probabilities).
* Email arrivals (delays, bounce rate).
* Timers (reminders; simulated “someone nudges you”).
* Browser interrupts (cookie banner/newsletter modal arrival).

```python
class EventBus:
    def __init__(self, seed: int):
        self.rng = LCG(seed); self.t=0; self.q=[]  # min-heap of (t_ms, event)
    def schedule(self, dt_ms: int, evt: dict): heappush(self.q, (self.t+dt_ms, evt))
    def next(self) -> dict: self.t, evt = heappop(self.q); return evt
```

The router drains at most one event between agent steps (configurable), exposing it in `observation.pending_events` and surfacing it to the relevant connector.

---

# Observation & action model (RL‑friendly on top of MCP)

**Observation (always):**

```json
{
  "time_ms": 123456,
  "focus": "browser|slack|mail",
  "summary": "short textual snapshot (page excerpt or latest messages)",
  "screenshot_ref": "blob://..." ,
  "action_menu": [
    {"tool":"browser.click","args":{"node_id":"CLICK:add_to_cart#0"}},
    {"tool":"slack.send_message","args":{"channel":"#procurement","text":"..."}},
    {"tool":"mail.compose","args_schema":{"to":"str","subj":"str","body_text":"str"}}
  ],
  "pending_events": {"slack":1,"mail":0}
}
```

**Action (one MCP call)**: the agent chooses a tool+args (from menu or free‑form if permitted). VEI executes the call against the selected backend, logs it, and advances the event bus.

**Why action menus**: constrain action space to **visible affordances** and **well‑typed tool calls**, stabilizing RL while remaining MCP‑native.

---

# Deterministic Replay (two layers)

1. **Tools replay (`.mcpz`)**

   * Sequence of `{tool, args_signature, request, response, dt_ms, t_start}`.
   * Webhook/events recorded and re‑emitted into Event Bus at `t_start + dt_ms`.
   * Matching on **(tool name + normalized args signature)**; mismatches → `invalid_action`.

2. **Browser replay (`.wacz` + DOM‑graph)**

   * Node: `{dom_id, url, page_type, excerpt, screenshot_hash}`.
   * Edge: `{alias: "CLICK:selector_hash", next_dom_id, constraints?}`.
   * Playwright serves assets from `.wacz/.har`; transitions gated by **alias → node** mapping so **(state, action) → next state** is pure.

Determinism guarantees:

* Fixed seed + `.mcpz/.wacz` + Chromium build hash → **bit‑for‑bit** identical episode (DOM hashes, tool payloads, timings).

---

# Scoring (execution‑based, zero vibes)

**v1 Task family: “Research → Slack approval → Email request → Email parse”**

* **Terminal success** requires:

  * **Browser**: extract named facts with provenance (CSS path + URL hash).
  * **Slack**: send summary to `#procurement`; receive approval emoji `:white_check_mark:` or text “Approved”.
  * **Email**: compose vendor request; receive reply; parse ETA and price; echo back a structured summary.
* **Shaping**: partial flags (citations present; message sent in correct channel; email delivered; ETA parsed).
* **Costs**: actions, simulated wall‑time, tokens (if tool‑calling LLM).
* **Security (optional overlay)**: inject benign distractors (off‑topic Slack pings) and mild prompt‑injections in page text; track **ASR** separately.

Score object:

```json
{
  "success": true,
  "subgoals": {"citations":1,"approval":1,"email_sent":1,"email_parsed":1},
  "costs": {"actions":29,"wall_ms":37120,"tokens":11800},
  "provenance_ok": true,
  "artifacts": {"mcpz":"sha256:...","wacz":"sha256:...","screens":"dir://..."}
}
```

---

# Data & fixtures (v1)

* **Browser Replay**: 2–3 curated WACZ snapshots (e.g., two product pages + a neutral review page). Each with DOM‑graph edges for

  * follow link → PDP
  * open specs tab
  * capture quoted text
* **SlackSim personas**:

  * `@cfo`: replies with normal distribution around 12s; 10% “need clearer budget” derail; understands ✅/❌.
  * `@itops`: slower, can add a link; 20% off‑topic.
* **Email**:

  * Live local (Mailpit) for v1; templates for vendor replies (vary casing, signatures, quoted text).

---

# Safety & compliance (v1)

* **No external PII**; all fixtures synthetic.
* **Browser Live** (if used): domain whitelist; block POST; respect robots; **abort** if test markers absent.
* **Slack Live** (if attempted): dev workspace only; rate governor.
* **Auditability**: sign `.mcpz` and `.wacz` manifests (SHA‑256); store Chromium build/version.

---

# Minimal file layout

```
vei/
  router/                 # MCP router (single entry server)
    server.py             # mounts connectors, enforces seed/mode
    config.py
    event_bus.py
    action_menu.py
    logging.py            # writes .mcpz, screenshots, manifests
  connectors/
    slack_sim.py          # MCP server implementation (sim)
    slack_replay.py
    slack_live.py         # optional dev workspace
    mail_live_local.py    # Mailpit wrapper as MCP
    mail_sim.py
    mail_replay.py
    browser_replay.py     # WACZ + DOM-graph + Playwright
    browser_live.py       # whitelisted, guardrailed
  replay/
    traces/*.mcpz         # tool/webhook bundles
    web/*.wacz            # archives
    dom_graph/*.jsonl     # nodes/edges
  scoring/
    rules.py              # execution-based checks
  cli/
    vei_run.py            # run an episode
    vei_record.py         # capture Live → Replay
    vei_score.py          # produce a score JSON
  docs/
    MCP_TOOLS.md          # tool schemas
    TRACE_SPEC.md         # .mcpz format
    REPLAY.md             # determinism guarantees
```

---

# Core algorithms (pseudocode)

**Router loop**

```python
def step(agent_call):
    # 1) Execute one MCP tool call
    result = connectors[agent_call.tool].execute(agent_call.args)

    # 2) Log to .mcpz (if in replay/live)
    tracer.record(agent_call, result)

    # 3) Drain at most one scheduled event
    evt = bus.next_if_due()
    if evt:
        emitted = connectors[evt.target].deliver(evt)
        tracer.record_event(emitted)

    # 4) Build observation (summary + action_menu)
    obs = build_obs(focus=pick_focus(result, evt), connectors)
    return obs
```

**Action menu (browser)**

```python
def derive_affordances(readout, goal):
    nodes = visible_nodes(readout.axtree)
    ranked = rank_by(goal_similarity(nodes, goal), role_priors, historical_clicks)
    return [{"tool":"browser.click","args":{"node_id":alias(n)}} for n in topk(ranked)]
```

**Replay matching (`.mcpz`)**

```python
sig = normalize(tool, args)
rec = trace.lookup(sig, cursor)
if not rec: return error("invalid_action")
sleep(rec.dt_ms)   # or schedule via bus
return rec.response
```

---

# Determinism contract (what you can safely claim)

* **Fixed seed + fixed artifacts + fixed build** ⇒ identical:

  * Tool call sequence and payloads (`.mcpz`)
  * Event timings and order (Slack/Email)
  * Browser DOM node hashes per step (`.wacz` + DOM‑graph)
  * Screenshots bytes (given fixed GPU flags & viewport)

Any deviation is a bug in capture or an unsupported action: report as `invalid_action`, never “half‑live.”

---

# v1 demo scenario (scriptable)

1. **Replay**:

   * Goal: “Research laptop X vs Y; post Slack summary; email vendor; parse reply; post final summary.”
   * Agent runs; SlackSim approves; Email (Mailpit) replies per seed; score green.
2. **Live Browser subset**:

   * Open one whitelisted real page (read‑only); capture → create `.wacz`.
   * Re‑run same episode **entirely in replay** from fresh capture; show identical outcome.
3. **Seed sweep**:

   * Run seeds `[101, 202, 303]`; show success/steps; Slack off‑topic appears in one seed; agent recovers.

Artifacts handed to lab:

* `demo-acme_v1.wacz`, `demo-acme_v1.mcpz`, `manifest.json` (hashes), `score.json`, and **instructions to reproduce** via `vei_run.py`.

---

# Test plan (must pass)

* **Replay determinism**: SHA‑256 identical screenshots/DOM/action logs across 10 runs (same seed).
* **Event determinism**: Slack/Email event order & timestamps stable for a seed.
* **Invalid action handling**: out‑of‑menu MCP calls produce deterministic `invalid_action`.
* **Scoring robustness**: perturb emails (reordered quotes, casing) → parser still extracts ETA/price; missing citation → `provenance_ok=false`.
* **Safety**: Live browser cannot POST; Mailpit quarantined; logs contain no secrets.

---

# What not to do in v1

* Don’t include payments/returns; reduces variables.
* Don’t allow arbitrary CSS/JS execution via MCP; keep to **visible, typed affordances** and tool schemas.
* Don’t ship non‑replayable evals; every public number must be backed by `.mcpz/.wacz` + seed.

---

# What to do after v1 (directional)

* Swap SlackSim → Slack Live (dev workspace) + Replay capture.
* Add Jira/Confluence MCP connectors (Sim + Replay) for ticketed workflows.
* Introduce Security Pack (prompt‑injection suites; ASR).
* Tenant packs: seed company‑specific Slack topology + email templates + curated web archives.

---

This is the minimal, principled slice: **MCP‑native**, **seeded async**, **Live↔Replay↔Sim** behind one router, with **execution‑based scoring** and **signed audit artifacts**. It’s constrained enough to be buildable, rich enough to be valuable, and honest enough to be trusted.
