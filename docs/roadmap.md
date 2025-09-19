# VEI Realism Roadmap

## Guiding Principles
- Grow scope slowly; gate every leap behind deterministic tests and docs.
- Simulate external systems locally; no live SaaS calls in default flows.
- Prefer deterministic scripts for background activity before introducing additional LLMs.
- Preserve stdio-first transport and reproducibility (seed + config).

## Phase 0 — Foundation & Documentation (current)
- Capture roadmap and configuration guidelines (this document).
- Audit existing CLI/tests for baseline behaviour; ensure status quo passes.
- Define configuration surface for upcoming phases (`VEI_STATE_DIR`, `VEI_FAULT_PROFILE`, etc.) without wiring yet.
- Deliverable: documented plan, green tests.

### Preview: Config Surface Additions
- `VEI_STATE_DIR`: opt-in location for snapshots and receipts (future use).
- `VEI_FAULT_PROFILE`: `off|light|aggressive` toggle for chaos injectors.
- `VEI_DRIFT_SEED`: dedicated RNG seed for background drift jobs.
- `VEI_DRIFT_MODE`: `off|light|fast|aggressive` enabling scripted background activity.
- `VEI_MONITORS`: comma-separated list of monitors to enable by default.
- `VEI_SCENARIO_PACK`: name of prebuilt scenario collection to preload.

## Phase 1 — Modular State & Tool Registry (1–2 sprints)
- Introduce event-sourced `StateStore` (append-only log + snapshot API) powering router.
- Add pluggable tool registry describing side effects, permissions, synthetic cost/latency.
- Keep connectors purely simulated; adapt existing tools to read/write via `StateStore`.
- Update stdio router to emit signed receipts and reference state revisions.
- ✅ In-progress: state + receipts now persist to `VEI_STATE_DIR`, inspectable via `vei-state`.
- Deliverable: deterministic scenario replay, basic receipts, new unit tests.

## Phase 2 — Light Drift & Background Activity (1 sprint)
- Add scripted drift jobs (newsletters, approvals) that mutate state on timers.
- Implement opt-in background actors via deterministic scripts (no extra LLMs yet).
- Surface drift controls via CLI/ENV (`vei-drift --rate`, `VEI_DRIFT_SEED`).
- Extend tests to cover drift determinism under fixed seeds.
- Deliverable: agents see evolving inbox/docs while runs remain reproducible.

## Phase 3 — Policy & Monitoring Layer (1 sprint)
- Implement tool-aware monitor that inspects state diffs and synthetic costs. *(Tool-aware monitor scaffolded; next up: policy rules.)*
- Add lightweight policy engine (Python rules) enforcing budget/compliance checks.
- ✅ Policy engine promotes monitor findings (`VEI_POLICY_PROMOTE` env) and records results in state snapshots + scoring output.
- Extend scoring to report task success + policy/cost metrics.
- Deliverable: `vei-score` outputs multi-axis scores; monitors flag violations.

## Phase 4 — Advanced Interaction & Optional NPC Agents (stretch)
- Introduce optional background actors driven by small/local LLMs or scripted behaviour.
  - Start with canned templates; allow plugging in other models via interface.
  - Keep disabled by default; require explicit config to avoid extra dependencies.
- Add more fault profiles (rate limits, retries) once monitoring is stable.
- Deliverable: richer multi-party exchanges without sacrificing determinism.

## Deferring For Later
- Real live connectors (IMAP/SMTP, Playwright) — design but keep behind extras post Phase 2.
- Security sandboxing / micro-VMs — plan once state/monitoring solid.

## Immediate Next Steps
1. Confirm baseline tests (`pytest -q`).
2. Introduce placeholder config entries and state-store scaffolding (no behaviour change).
3. Add design docs/examples for tool registry APIs before refactoring.
