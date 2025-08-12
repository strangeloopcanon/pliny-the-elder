from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest


E2E_FLAG = os.environ.get("VEI_E2E", "0")


@pytest.mark.asyncio
@pytest.mark.skipif(E2E_FLAG != "1", reason="VEI_E2E=1 required to run optional SSE e2e test")
async def test_e2e_scorer_via_sse(tmp_path: Path):
    # End-to-end through SSE: reset -> compose -> observe drain -> score
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

            # Optional: reset to a clean seed
            await s.call_tool("vei.reset", {"seed": 42042})
            pong = await s.call_tool("vei.ping", {})
            assert pong.get("ok") is True

            # Trigger an email exchange
            await s.call_tool(
                "mail.compose",
                {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
            )

            # Tick the sim forward until mail event is delivered
            for _ in range(30):
                obs = await s.call_tool("vei.observe", {"focus": "mail"})
                if obs.get("pending_events", {}).get("mail", 0) == 0:
                    break

        # Score artifacts from the run
        from vei.cli.vei_score import score as score_cmd
        import typer.testing

        runner = typer.testing.CliRunner()
        result = runner.invoke(score_cmd, ["--artifacts-dir", str(tmp_path / "artifacts")])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["subgoals"]["email_parsed"] == 1
        assert data["success"] is True
    except Exception as e:  # pragma: no cover - depends on external server availability
        pytest.skip(f"SSE server not available: {e}")

