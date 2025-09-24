# VEI Simulation & RL Plan

This document outlines how VEI should evolve to support realistic, data-driven virtual office environments for training and evaluating agents, even when real enterprise traces are not available. It covers simulation modes, synthetic content, agent behavior, RL training pipelines, replay readiness, and how to integrate new tools (e.g., Salesforce or Oracle Cloud) in a deterministic, testable way.

## 1. Principles & Objectives
- Deterministic first: identical outcomes for a fixed seed and configuration.
- Stdio-first dev/test; SSE optional. No hidden network dependencies by default.
- Pluggable worlds: sim, semi-sim (guided), and replay from real traces.
- Observability baked-in: structured traces, state snapshots, scoring, and policy/monitor signals.
- Narrow, composable interfaces: small, testable components; clear schemas.
- Continuous execution: proceed through milestones sequentially without requiring sprint-by-sprint approval, keeping changes modular.

## 1.1 Execution Cadence & Testing Rhythm
- Work through the roadmap in order (Simulation Foundation → Behavior/RL → Replay) with compact, reviewable commits but no pauses waiting for approval between phases.
- After each major batch, run targeted pytest subsets; at least once mid-plan (after Behavior/RL deliverables) execute the live LLM test `pytest -q -k llm_stdio_smoke` assuming `.env` exposes `OPENAI_API_KEY`.
- Maintain parsimony: new modules should be thin adapters around existing primitives, with shared utilities centralized when reuse emerges instead of duplicating logic.

## 2. Simulation Without Enterprise Traces
When we do not yet have enterprise logs, we still want breadth and realism. We achieve this with a Scenario DSL, synthetic content packs, and deterministic world twins.

### 2.1 Scenario DSL (templated)
- New module: `vei/world/scene_dsl.py` with pydantic schemas describing:
  - Participants (actors, roles, email addresses, Slack handles).
  - Channels (Slack channels, mail folders, doc spaces, calendars).
  - World graph (browser nodes, docs index, tickets, CRM entities).
  - Triggers and timers (pre-scheduled derailments, follow-ups).
  - Vendor templates (price, ETA ranges) and policy constraints (budgets, approval requirements).
- Compiler: `vei/world/compiler.py`
  - Inputs: DSL JSON/YAML + seed.
  - Outputs: a `Scenario` object + initial EventBus schedules + seeded content stores.
  - Deterministic sampling within ranges (reuse LCG or `random.Random(seed)`).

### 2.2 Synthetic Content Packs
- Docs twin (new): `docs.*` tools backed by a `DocumentStore`:
  - `docs.create`, `docs.update`, `docs.read`, `docs.search`, `docs.list`.
  - Backed by seeded corpus (Markdown/HTML snippets with citations, product sheets, policies).
  - Optional template injector to embed prices/specs consistent with scenario vendors.
- Calendar twin (new): `calendar.*`:
  - `calendar.create_event`, `calendar.list_events`, `calendar.accept`, `calendar.decline`.
  - Integrates with mail (invite emails) and Slack reminders.
- Tickets twin (new): `tickets.*`:
  - `tickets.create`, `tickets.update`, `tickets.transition`, `tickets.get`, `tickets.list`.
  - Used to model approval workflows and SLAs.
- Existing Slack/Mail/Browser/ERP/CRM are retained and enriched to cross-reference docs, calendar invites, and tickets.

### 2.3 Event Orchestration
- EventBus remains the canonical clock. Scenario compiler returns an initial schedule:
  - Seeded derailments (off-topic Slack pings).
  - Vendor reply windows (mail inbound events based on composed outbound).
  - Ticket state changes and reminders.
- Twins consume/produce events deterministically; latency modeled via ToolRegistry profiles.

### 2.4 Determinism & Fault Profiles
- Extend `ToolRegistry` metadata (non-breaking option) to include latency distribution parameters and error rates per tool (mirroring ERP).
- `VEI_FAULT_PROFILE` selects canned profiles (e.g., `off`, `light`, `spiky`) to inject retries/errors deterministically.

## 3. Action Selection Strategies (LLM, Scripted, RL)
- LLM-driven (existing): via `vei/cli/vei_chat.py` and `vei-llm-test` for demos/evals.
- Scripted “teacher” policies: lightweight behavior trees/options for baseline completion and to bootstrap datasets.
  - New: `vei/behavior/trees.py` and `vei/behavior/memory.py` (SQLite-backed episodic memory of facts like vendor prices, approvals, doc links).
- RL-driven: agents learn to select tools and fill arguments via `VEIEnv` (see Section 4). No LLM required; useful for robust, cost-aware policies.

## 4. RL Training Pipeline
We expand `vei/rl/env.py` into a richer, Gymnasium-compatible environment and provide wrappers/utilities for training and evaluation.

### 4.1 Environment API
- Keep `VEIEnv` core; add wrappers under `vei/rl/`:
  - `wrappers/action_mask.py`: masks invalid tools (not in `action_menu`).
  - `wrappers/arg_spaces.py`: builds argument spaces per tool from pydantic arg models (see server_fastmcp tool arg definitions) or lightweight arg schemas.
  - `wrappers/flatten_obs.py`: feature-extract the observation (pending counts, focus, menu embeddings).
  - `vector/env_vec.py`: simple vectorized env for throughput.

### 4.2 Action Space Design
- Two-headed policy:
  - Discrete head: pick a tool from current `action_menu` (index into menu).
  - Argument head(s): per-tool typed heads built from schemas:
    - Categorical (channel names, node ids) → discrete softmax.
    - Text/lightweight numeric (amounts) → templated generators with slot-filling from memory/context to keep space finite.
    - For free-form text, restrict to a small set of templates (e.g., “Please approve budget $X for Y”).
- Invalid action penalty: selecting a tool not in menu or failing schema yields small negative reward and no-op.

### 4.3 Rewards & Termination
- Sparse: +1 when vendor email parsed (price+eta from mail event), else 0.
- Dense shaping (existing): +0.25 for each subgoal: citations, approval, email_sent, email_parsed.
- Policy/monitor-aware penalties: e.g., `slack.approval_missing_amount` → −0.05; repeated tool usage → −0.01 at thresholds.
- Cost penalty: proportional to actions and simulated time.
- Termination: success, or drained pending events after sending email, or step/time caps.

### 4.4 Datasets for Offline Learning
- Without real traces: generate scripted rollouts via teacher policies; store as canonical episodes (obs, action, reward, done, info) in `.vei.ep.jsonl`.
- When real traces exist: align canonical events to tool calls to create imitation pairs; fall back to semi-supervised targets when args are ambiguous (see 6).

### 4.5 Training Harness
- New CLI: `vei-train` with subcommands (BC, PPO, A2C). Uses local implementations or optional extras for popular libs. No external network.
- `vei-eval` to run fixed seeds over scenario packs, produce `trace.jsonl`, and compute `vei.score_core` metrics.
- Logging: write run configs and metrics to `_vei_out/train_*` and snapshots of policies.

## 5. Adding New Tools & Twins (e.g., Salesforce, Oracle Cloud)
This mirrors existing `ErpSim` and `CrmSim` but provides a clear checklist.

### 5.1 Checklist
1) Define twin class: `vei/router/salesforce.py` or `oracle_cloud.py` with deterministic internal stores and methods (tools). Keep amounts in integer cents; keep IDs stable and seeded.
2) Define pydantic arg models in `server_fastmcp.py` (or a sibling) and map MCP tool names to twin methods.
3) Register in `ToolRegistry` with metadata (description, side_effects, permissions, latency, cost).
4) Add alias packs in `vei/router/alias_packs.py` mapping branded names to core tool names.
5) Extend `Router` to instantiate the twin (optional import guarded like ERP/CRM).
6) Add scenario DSL hooks so the compiler can pre-seed records/entities (e.g., accounts, contacts, opportunities).
7) Monitors: add domain monitors (e.g., `crm.stage_skips`, `oracle.payment_violation`). Wire to policy promotion.
8) Scoring: add a domain score pack (e.g., close-won opportunity flow).
9) Tests: unit tests for twin behavior; integration tests via stdio transport for at least one happy path; alias pack tests.

### 5.2 Example Tool Set (Salesforce-like)
- `crm.create_contact`, `crm.get_contact`, `crm.list_contacts`
- `crm.create_company`, `crm.get_company`, `crm.list_companies`
- `crm.create_deal`, `crm.get_deal`, `crm.list_deals`, `crm.update_deal_stage`
- `crm.log_activity`

### 5.3 Example Tool Set (Oracle Cloud ERP-like)
- `erp.create_po`, `erp.get_po`, `erp.list_pos`
- `erp.receive_goods`, `erp.submit_invoice`, `erp.get_invoice`, `erp.list_invoices`
- `erp.match_three_way`, `erp.post_payment`
- Deterministic error injection via `VEI_ERP_ERROR_RATE` (already present).

## 6. Replay & Semi‑Sim Readiness
- Canonical dataset schema (`vei/data/models.py`) for events with envelope fields: `time_ms`, `actor_id`, `channel`, `type`, `payload`, `correlation_id`.
- Ingestion CLIs (future): `vei-import slack|mbox|jira ...` → `.vei.jsonl` with seeded pseudonymization (`vei/data/anonymize.py`).
- Replay adapter: `vei/world/replay.py` that schedules dataset events on the EventBus.
- Semi‑sim: constrain outcomes using a sliding window of dataset events; off‑policy agent actions snap to closest valid next events; fall back to sim when diverging.

## 7. Observability, Scoring, and Policy
- Trace v2 additions: `run_id`, `scenario_id`, `correlation_id`, `parent_event`, `actor`. Keep `trace.jsonl` append-only, stream-capable.
- Score packs: procurement (existing), CRM opportunity, ticket SLA, calendar coordination.
- Policy engine (existing) ingests monitor findings; expand default rules and tie to reward penalties.

## 8. Security & Governance
- Pseudonymization by default for imported datasets; deterministic mapping with seed.
- Redaction rules for PII hotspots; content hashing for provenance.
- Optional encryption-at-rest for dataset files.

## 9. Milestones & Deliverables

### Sprint A (2 weeks): Simulation Foundation
- Scene DSL + compiler (`vei/world/scene_dsl.py`, `vei/world/compiler.py`).
- Docs twin + Calendar twin + Tickets twin minimal implementations.
- ToolRegistry latency/error profiles (non-breaking addition) + fault profiles.
- Monitors: `slack.approval_format`, `email.subject_quality`, basic `pii.leak` regex.
- CLI: `vei-scenarios` extended to list/validate DSL packs.
- Tests: unit for compiler and twins; integration: stdio run across default pack.
- Post-batch check: run `pytest -q` (core suite) before progressing.

### Sprint B (2 weeks): Behavior v1 + RL Env
- Behavior trees + memory store (`vei/behavior/*`), scripted teachers for procurement.
- RL wrappers: action mask, arg spaces, feature extractor; vectorized env.
- CLIs: `vei-train` (BC baseline) and `vei-eval` (score + policy findings).
- Tests: RL env action validity, reward correctness, deterministic rollouts.
- Mid-plan live LLM test: execute `pytest -q -k llm_stdio_smoke` (requires valid `OPENAI_API_KEY`).

### Sprint C (2 weeks): Semi‑Sim & Replay Hooks
- Canonical event models (`vei/data/models.py`) and stub importers.
- Replay adapter to EventBus; semi-sim windowing.
- CLI: `vei-pack` to package scenario packs (.jsonl + assets) and metadata.
- Tests: replay determinism; semi-sim snap-to-window behavior.
- Final validation: full `pytest -q` plus `vei-smoke --transport stdio` to confirm end-to-end stability.

## 10. Risks & Mitigations
- Argument space explosion → templated text generation and typed heads; leverage scenario compiler for canonical channels/entities.
- Non-determinism via time/process → centralize randomness through LCG and seed propagation; avoid wall-clock anywhere critical.
- Scope creep in twins → prioritize minimal tool surfaces tied to scoring and monitors.
- Dataset governance → enforce pseudonymization + lints at import time.

## 11. Acceptance Criteria (End-to-End)
- With no real traces: run a seeded scenario pack, complete procurement and CRM-lite flows via scripted policy and RL baseline, produce `trace.jsonl`, score success with zero errors, and deterministic re-runs.
- With traces (later): import → anonymize → pack → replay or semi-sim; same scenario passes stdio smoke and scoring gates.

---

Appendix: Implementation Pointers
- Integrate new tools by following the ERP/CRM patterns: twin class → MCP tool mapping → ToolRegistry → alias packs → monitors → scoring → tests.
- Build RL argument spaces using the pydantic arg definitions already declared for tools in `vei/router/server_fastmcp.py`.
- Keep tests stdio-first and seeded; avoid network and LLMs unless explicitly marked.
