from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import AsyncOpenAI
from ._llm_loop import extract_plan


def _normalize_result(res: object) -> dict:
    # Accept raw dicts
    if isinstance(res, dict):
        return res
    # MCP CallToolResult (structuredContent or content list)
    sc = getattr(res, "structuredContent", None)
    if sc is not None:
        if isinstance(sc, dict):
            return sc
        # Some clients may return a list for structured content
        try:
            if sc and isinstance(sc, list):
                return sc[0] if isinstance(sc[0], dict) else {"value": sc[0]}
        except Exception:
            ...
    content = getattr(res, "content", None)
    if isinstance(content, list):
        for item in content:
            try:
                t = item.get("type")
                if t == "json" and "data" in item:
                    return item["data"]
                if t == "text" and "text" in item:
                    import json as _json
                    try:
                        return _json.loads(item["text"])
                    except Exception:
                        return {"text": item["text"]}
            except Exception:
                continue
    return {}

app = typer.Typer(add_completion=False)


SYSTEM_PROMPT = (
    "You are an assistant controlling tools via MCP in a synthetic enterprise world. "
    "Each step: first call 'vei.observe' to see the action_menu, then pick exactly one tool to call. "
    "Goal: research the product page, send a Slack approval summary to #procurement, compose a vendor email,"
    " and wait for the reply (may take multiple observe steps). Keep steps minimal."
)


async def call_mcp_tool(session: ClientSession, tool: str, args: dict) -> dict:
    return await session.call_tool(tool, args)


async def run_episode(
    model: str,
    sse_url: str,  # kept for signature compatibility; ignored in stdio mode
    max_steps: int = 12,
    openai_base_url: str | None = None,
    openai_api_key: str | None = None,
    task: str | None = None,
) -> list[dict]:
    # stdio-only transport
    py = os.environ.get("PYTHON", None) or (sys.executable if 'sys' in globals() else None)
    if not py:
        import sys as _sys
        py = _sys.executable or "python3"
    params = StdioServerParameters(command=py, args=["-m", "vei.router"], env={**os.environ, "VEI_DISABLE_AUTOSTART": "1"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # OpenAI Responses API for gpt-5 family; no temperature parameter
            client = AsyncOpenAI(
                base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
                api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
            )
            base_prompt = SYSTEM_PROMPT
            if task:
                base_prompt += f"\nTask: {task}"
            transcript: list[dict] = []

            for step in range(max_steps):
                obs_raw = await call_mcp_tool(session, "vei.observe", {})
                obs = _normalize_result(obs_raw)
                transcript.append({"observation": obs})
                menu = obs.get("action_menu", [])
                menu_text = "\n".join(
                    f"- {m.get('tool')} {json.dumps(m.get('args', m.get('args_schema', {})))}" for m in menu
                )
                user = (
                    f"Time: {obs.get('time_ms')}\nFocus: {obs.get('focus')}\nSummary: {obs.get('summary')}\n"
                    f"Pending: {json.dumps(obs.get('pending_events'))}\n"
                    f"Action menu (choose ONE tool and JSON args):\n{menu_text}\n"
                    "Reply STRICTLY as JSON with fields {\"tool\": str, \"args\": object}."
                )
                # Responses API call; enforce JSON object output
                resp = await client.responses.create(
                    model=model,
                    input=f"{base_prompt}\n\n{user}\nReturn a JSON object only.",
                )
                raw = getattr(resp, "output_text", None)
                if not raw:
                    # Fallback traversal of SDK response
                    try:
                        out = getattr(resp, "output", [])
                        if out and hasattr(out[0], "content"):
                            cnt = out[0].content
                            if cnt and hasattr(cnt[0], "text"):
                                raw = cnt[0].text
                    except Exception:
                        raw = "{}"
                if not raw:
                    raw = "{}"
                plan = extract_plan(raw, default_tool="browser.read")
                tool = plan.get("tool", "browser.read")
                args = plan.get("args", {})
                res_raw = await call_mcp_tool(session, tool, args)
                res = _normalize_result(res_raw)
                transcript.append({"action": {"tool": tool, "args": args, "result": res}})

            return transcript


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
    import sys as _sys
    subprocess.Popen([_sys.executable or "python3", "-m", "vei.router.sse"], env=env)
    for _ in range(20):
        if _port_open(host, port):
            break
        time.sleep(0.1)


@app.command()
def run(
    model: str = typer.Option("gpt-5", help="OpenAI model id (see latest-model guide)"),
    openai_base_url: str | None = typer.Option(None, help="Override OPENAI_BASE_URL for SDK (OpenAI-compatible)"),
    openai_api_key: str | None = typer.Option(None, help="Override OPENAI_API_KEY for SDK"),
    max_steps: int = typer.Option(12, help="Max tool steps"),
    task: str | None = typer.Option(None, help="High-level goal for the LLM (prefixed as 'Task: ...')"),
) -> None:
    load_dotenv(override=True)
    if not os.getenv("OPENAI_API_KEY"):
        raise typer.BadParameter("OPENAI_API_KEY not set (put it in .env)")
    transcript = asyncio.run(
        run_episode(
            model=model,
            sse_url="",  # unused in stdio mode
            max_steps=max_steps,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            task=task,
        )
    )
    typer.echo(json.dumps(transcript, indent=2))


if __name__ == "__main__":
    app()
