Test setup (stdio-first)

- No server to pre-start: stdio tests spawn `python -m vei.router` automatically.
- Live LLM test requires an API key in environment or `.env` (OPENAI_API_KEY).

Run tests:

```bash
pytest -q
```

Live LLM test (optional):

```bash
# Ensure .env contains OPENAI_API_KEY (and optional OPENAI_BASE_URL)
pytest -q -k llm_stdio_smoke
```
