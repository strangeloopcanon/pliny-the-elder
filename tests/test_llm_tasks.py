from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
pytestmark = pytest.mark.skipif(os.environ.get("VEI_SSE", "0") != "1", reason="VEI_SSE=1 required for SSE tests")
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse")


async def mcp_call(url: str, tool: str, args: dict) -> dict:
    async with sse_client(url) as (read, write):
        session = ClientSession(read, write)
        await session.initialize()
        return await session.call_tool(tool, args)


@pytest.mark.asyncio
async def test_observe_and_minimal_flow():
    obs = await mcp_call(SSE_URL, "vei.observe", {})
    assert "action_menu" in obs
    assert "summary" in obs

    res = await mcp_call(SSE_URL, "browser.read", {})
    assert "title" in res

    res = await mcp_call(SSE_URL, "slack.send_message", {"channel": "#procurement", "text": "Posting summary for approval"})
    assert "ts" in res

    res = await mcp_call(
        SSE_URL,
        "mail.compose",
        {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
    )
    assert "id" in res


@pytest.mark.asyncio
async def test_event_drain_and_scoring(tmp_path: Path):
    out = tmp_path / "artifacts"
    os.environ["VEI_ARTIFACTS_DIR"] = str(out)

    # Trigger events
    await mcp_call(SSE_URL, "slack.send_message", {"channel": "#procurement", "text": "Posting summary for approval"})
    await mcp_call(
        SSE_URL,
        "mail.compose",
        {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
    )
    # Drain via repeated observe
    for _ in range(20):
        obs = await mcp_call(SSE_URL, "vei.observe", {})
        if obs.get("pending_events", {}).get("mail", 0) == 0 and obs.get("pending_events", {}).get("slack", 0) == 0:
            break

    # Score
    from vei.cli.vei_score import score as score_cmd
    import typer.testing

    runner = typer.testing.CliRunner()
    result = runner.invoke(score_cmd, ["--artifacts-dir", str(out)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["success"] is True
    assert data["subgoals"]["email_parsed"] == 1

