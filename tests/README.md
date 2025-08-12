Test setup (SSE transport)

- Start the SSE server in a terminal:

```bash
VEI_SEED=42042 python -m vei.router.sse
```

- Default SSE URL: `http://127.0.0.1:3001/sse`.
  - Message POST endpoint (for non-SSE clients): `http://127.0.0.1:3001/messages/`.
  - Override SSE URL with `VEI_SSE_URL` env for tests.

- Run tests:

```bash
pytest -q
```

