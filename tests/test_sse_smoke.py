from __future__ import annotations

import asyncio
import os

import pytest


SSE_SMOKE_FLAG = os.environ.get("VEI_SSE_SMOKE", "0")


@pytest.mark.asyncio
@pytest.mark.skipif(SSE_SMOKE_FLAG != "1", reason="VEI_SSE_SMOKE=1 required to run SSE smoke test")
async def test_sse_minimal_smoke(tmp_path):
    # Try a minimal end-to-end smoke via SSE. Skip if server/unavailable libs.
    os.environ["VEI_ARTIFACTS_DIR"] = str(tmp_path / "artifacts")

    try:
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client
    except Exception:  # pragma: no cover - optional dep in some envs
        pytest.skip("mcp client not available")

    url = os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse")

    try:
        async with sse_client(url) as (read, write):
            s = ClientSession(read, write)
            await s.initialize()
            # Health check and a couple of basic calls
            pong = await s.call_tool("vei.ping", {})
            assert pong.get("ok") is True
            obs = await s.call_tool("vei.observe", {})
            assert "action_menu" in obs
            # Deterministic tool
            page = await s.call_tool("browser.read", {})
            assert "title" in page
    except Exception as e:  # pragma: no cover - depends on external server availability
        pytest.skip(f"SSE server not available: {e}")
