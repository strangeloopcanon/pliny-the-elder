# Repository Guidelines

## Project Structure & Modules
- `vei/`: core package (router, SSE server, CLI). Key modules: `vei/router/*`, `vei/cli/*`, `vei/world/*`.
- `tests/`: pytest suite (stdio-first transport tests, scoring, scenarios).
- `examples/`: minimal clients and router loops.
- `_vei_out/` and `.artifacts/`: run artifacts, traces, logs (gitignored).
- `pyproject.toml`: package, extras, and console scripts.

## Build, Test, and Dev Commands
- Install (with extras): `pip install -e ".[llm,browser,sse]"`
- Quick setup check: `python test_vei_setup.py`
- Run tests: `pytest -q`
- Transport smoke (no API key): `vei-smoke --transport stdio --timeout-s 30`
- Demo and CLI: `vei-demo --mode llm --model gpt-5 --artifacts-dir ./_vei_out/demo`
- Start SSE server (optional): `VEI_SEED=42042 python -m vei.router.sse`

## Coding Style & Conventions
- Language: Python 3.11+, 4‑space indent, PEP8.
- Types: prefer type hints and `pydantic` models for I/O payloads.
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, tests as `tests/test_*.py`.
- CLI: add Typer commands under `vei/cli/` and expose via `pyproject.toml` `[project.scripts]`.

## Testing Guidelines
- Framework: `pytest` (see `pytest.ini`). Target stdio first; SSE is optional.
- Determinism: respect `VEI_SEED` in tests; avoid real network/LLM unless explicitly marked.
- Add unit tests near feature area and an integration test if it touches the router/tools.
- Run locally: `pytest -q` or filter: `pytest -q -k transport`.

## Commit & Pull Requests
- Commit style: follow Conventional Commits seen in history (e.g., `feat:`, `fix:`, `chore:`). Keep subject ≤72 chars.
- PRs should include: concise description, linked issues, repro steps, and screenshots/log snippets when applicable (e.g., `_vei_out/.../trace.jsonl`).
- Add usage notes to `README.md` when introducing new CLI flags, tools, or env vars.

## Security & Config Tips
- Secrets: never commit `.env`; use `OPENAI_API_KEY` (optionally `OPENAI_BASE_URL`).
- Artifacts: `_vei_out/`, `**/artifacts/**`, and `**/trace.jsonl` are gitignored—do not add them to commits.
- Local MCP client config: `mcp.json` defines stdio transport (`python -m vei.router`).

## Architecture Overview
- Router exposes MCP tools: `slack.*`, `mail.*`, `browser.*`, `vei.*`.
- Two transports: stdio (default for dev/CI) and SSE (`vei.router.sse`). Keep new tools deterministic and replay‑friendly.

