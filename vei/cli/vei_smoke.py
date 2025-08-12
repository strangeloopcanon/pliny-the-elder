from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import typer
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import anyio

app = typer.Typer(add_completion=False)


async def run_once(seed: int) -> dict[str, Any]:
    params = StdioServerParameters(command="python3", args=["-m", "vei.router"], env={"VEI_SEED": str(seed)})
    async with stdio_client(params) as (read, write):
        session = ClientSession(read, write)
        await session.initialize()

        out: dict[str, Any] = {"steps": []}

        # Observe
        obs = await session.call_tool("vei.observe", {})
        out["steps"].append({"vei.observe": obs})
        typer.echo(json.dumps({"vei.observe": obs}))

        # Read browser
        res = await session.call_tool("browser.read", {})
        out["steps"].append({"browser.read": res})
        typer.echo(json.dumps({"browser.read": res}))

        # Send slack summary
        res = await session.call_tool("slack.send_message", {"channel": "#procurement", "text": "Posting summary for approval"})
        out["steps"].append({"slack.send_message": res})
        typer.echo(json.dumps({"slack.send_message": res}))

        # Compose email
        res = await session.call_tool(
            "mail.compose",
            {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
        )
        out["steps"].append({"mail.compose": res})
        typer.echo(json.dumps({"mail.compose": res}))

        # Tick observe until events drain (max 20 steps)
        for _ in range(20):
            obs = await session.call_tool("vei.observe", {})
            out["steps"].append({"vei.observe": obs})
            typer.echo(json.dumps({"vei.observe": obs}))
            pending = obs.get("pending_events", {})
            if (pending.get("slack", 0) == 0) and (pending.get("mail", 0) == 0):
                break

        return out


@app.command()
def run(seed: int = typer.Option(42042), timeout_s: int = typer.Option(30)) -> None:
    async def _runner():
        return await run_once(seed)
    res: dict | None = None
    try:
        res = asyncio.run(asyncio.wait_for(_runner(), timeout=timeout_s))
    except* anyio.BrokenResourceError:
        # Ignore stdio teardown noise when the child process exits fast
        ...
    finally:
        if res is not None:
            typer.echo(json.dumps(res, indent=2))


if __name__ == "__main__":
    app()


