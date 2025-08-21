from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import typer
import sys
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
import subprocess
import time
from urllib.parse import urlparse
import anyio

app = typer.Typer(add_completion=False)


async def run_once(
    seed: int,
    transport: str = "stdio",
    sse_url: str | None = None,
) -> dict[str, Any]:
    # Normalize MCP CallToolResult objects into JSON-safe dicts
    def _normalize_result(res: Any) -> dict:
        try:
            if getattr(res, "isError", False):
                return {"error": True, "content": getattr(res, "content", None)}
            sc = getattr(res, "structuredContent", None)
            if sc is not None:
                return sc
            content = getattr(res, "content", None)
            if content and isinstance(content, list) and getattr(content[0], "text", None):
                import json as _json
                txt = content[0].text
                try:
                    return _json.loads(txt)
                except Exception:
                    return {"text": txt}
            return {"result": res}
        except Exception:
            return {"result": str(res)}
    transport = (transport or "stdio").strip().lower()
    if transport == "sse":
        # Ensure server is up if a URL is given
        if sse_url:
            _ensure_sse_available(sse_url, autostart=True)
        ctx = sse_client(sse_url or os.getenv("VEI_SSE_URL", "http://127.0.0.1:3001/sse"))
    else:
        py = sys.executable or "python3"
        params = StdioServerParameters(command=py, args=["-m", "vei.router"], env={"VEI_SEED": str(seed)})
        ctx = stdio_client(params)

    async with ctx as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            out: dict[str, Any] = {"steps": []}

            # Observe
            obs_raw = await session.call_tool("vei.observe", {})
            obs = _normalize_result(obs_raw)
            out["steps"].append({"vei.observe": obs})
            typer.echo(json.dumps({"vei.observe": obs}))

            # Read browser
            res_raw = await session.call_tool("browser.read", {})
            res = _normalize_result(res_raw)
            out["steps"].append({"browser.read": res})
            typer.echo(json.dumps({"browser.read": res}))

            # Send slack summary
            res_raw = await session.call_tool("slack.send_message", {"channel": "#procurement", "text": "Posting summary for approval"})
            res = _normalize_result(res_raw)
            out["steps"].append({"slack.send_message": res})
            typer.echo(json.dumps({"slack.send_message": res}))

            # Compose email
            res_raw = await session.call_tool(
                "mail.compose",
                {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
            )
            res = _normalize_result(res_raw)
            out["steps"].append({"mail.compose": res})
            typer.echo(json.dumps({"mail.compose": res}))

            # Tick observe until events drain (max 20 steps)
            for _ in range(20):
                obs_raw = await session.call_tool("vei.observe", {})
                obs = _normalize_result(obs_raw)
                out["steps"].append({"vei.observe": obs})
                typer.echo(json.dumps({"vei.observe": obs}))
                pending = obs.get("pending_events", {})
                if (pending.get("slack", 0) == 0) and (pending.get("mail", 0) == 0):
                    break

            return out


def _ensure_sse_available(sse_url: str, autostart: bool) -> None:
    def _port_open(host: str, port: int) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((host, port)) == 0
            except Exception:
                return False
    parsed = urlparse(sse_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3001
    if _port_open(host, port):
        return
    if not autostart:
        return
    env = os.environ.copy()
    env.setdefault("VEI_HOST", host)
    env.setdefault("VEI_PORT", str(port))
    subprocess.Popen(["python", "-m", "vei.router.sse"], env=env)
    for _ in range(50):
        if _port_open(host, port):
            break
        time.sleep(0.1)


@app.command()
def run(
    seed: int = typer.Option(42042),
    timeout_s: int = typer.Option(30),
    transport: str = typer.Option("stdio", help="MCP transport: stdio or sse"),
    sse_url: str = typer.Option(os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse"), help="SSE URL when transport=sse"),
) -> None:
    async def _runner():
        return await run_once(seed, transport=transport, sse_url=sse_url)
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
