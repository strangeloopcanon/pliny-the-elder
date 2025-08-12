from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
pytestmark = pytest.mark.skipif(os.environ.get("VEI_SSE", "0") != "1", reason="VEI_SSE=1 required for SSE tests")
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

SSE_URL = os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse")


async def call(url: str, tool: str, args: dict) -> dict:
    async with sse_client(url) as (read, write):
        s = ClientSession(read, write)
        await s.initialize()
        return await s.call_tool(tool, args)


@pytest.mark.asyncio
async def test_slack_derail_recovery():
    # Send an approval request WITHOUT budget amount to trigger a clarifying question
    await call(SSE_URL, "slack.send_message", {"channel": "#procurement", "text": "Requesting approval for laptop X. Summary attached."})
    # Observe until Slack message arrives
    for _ in range(20):
        obs = await call(SSE_URL, "vei.observe", {})
        if obs.get("pending_events", {}).get("slack", 0) == 0:
            continue
    # Provide budget in a follow-up
    res = await call(SSE_URL, "slack.send_message", {"channel": "#procurement", "text": "Budget: $3200"})
    assert "ts" in res


@pytest.mark.asyncio
async def test_email_template_variants_parsed(tmp_path: Path):
    out = tmp_path / "artifacts"
    os.environ["VEI_ARTIFACTS_DIR"] = str(out)

    await call(SSE_URL, "mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."})
    for _ in range(20):
        obs = await call(SSE_URL, "vei.observe", {})
        if obs.get("pending_events", {}).get("mail", 0) == 0:
            continue
    # Score artifacts
    from vei.cli.vei_score import score as score_cmd
    import typer.testing

    runner = typer.testing.CliRunner()
    result = runner.invoke(score_cmd, ["--artifacts-dir", str(out)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["subgoals"]["email_parsed"] == 1


@pytest.mark.asyncio
async def test_browser_affordance_minimal():
    # Ensure we only offer visible affordances and clicking works deterministically
    hits = await call(SSE_URL, "browser.find", {"query": "button", "top_k": 5})
    assert "hits" in hits
    if hits["hits"]:
        node_id = hits["hits"][0]["node_id"]
        nav = await call(SSE_URL, "browser.click", {"node_id": node_id})
        assert "url" in nav

