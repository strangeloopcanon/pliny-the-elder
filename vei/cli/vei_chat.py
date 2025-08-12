from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from openai import AsyncOpenAI
from ._llm_loop import extract_plan


app = typer.Typer(add_completion=False)


SYSTEM_PROMPT = (
    "You are an assistant controlling tools via MCP in a synthetic enterprise world. "
    "Each step: first call 'vei.observe' to see the action_menu, then pick exactly one tool to call. "
    "Return STRICTLY a JSON object with fields {\"tool\": str, \"args\": object}."
)


async def call_mcp_tool(session: ClientSession, tool: str, args: dict) -> dict:
    return await session.call_tool(tool, args)


def extract_plan(raw: str) -> dict[str, Any]:  # Backward shim; import actual from helper
    return extract_plan(raw, default_tool="vei.observe")


async def loop(
    model: str,
    sse_url: str,
    max_steps: int,
    artifacts_dir: str | None,
    openai_base_url: str | None,
    openai_api_key: str | None,
    task: str | None,
) -> list[dict[str, Any]]:
    async with sse_client(sse_url) as (read, write):
        session = ClientSession(read, write)
        await session.initialize()

        client = AsyncOpenAI(
            base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
            api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
        )
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if task:
            messages.append({"role": "user", "content": f"Task: {task}"})
        transcript: list[dict[str, Any]] = []

        # Show help to the model
        try:
            help_obj = await call_mcp_tool(session, "vei.help", {})
            transcript.append({"help": help_obj})
        except Exception:
            ...

        for _ in range(max_steps):
            obs = await call_mcp_tool(session, "vei.observe", {})
            transcript.append({"observation": obs})
            menu = obs.get("action_menu", [])
            menu_text = "\n".join(
                f"- {m.get('tool')} {json.dumps(m.get('args', m.get('args_schema', {})))}" for m in menu
            )
            user = (
                f"Time: {obs.get('time_ms')}\n"
                f"Focus: {obs.get('focus')}\n"
                f"Summary: {obs.get('summary')}\n"
                f"Pending: {json.dumps(obs.get('pending_events'))}\n"
                f"Action menu (choose ONE):\n{menu_text}\n"
                "Reply strictly as JSON {\"tool\": str, \"args\": object}."
            )
            messages.append({"role": "user", "content": user})

            chat = await client.chat.completions.create(model=model, messages=messages, temperature=0)
            content = chat.choices[0].message.content or "{}"
            plan = extract_plan(content)

            tool = plan.get("tool", "vei.observe")
            args = plan.get("args", {})
            res = await call_mcp_tool(session, tool, args)
            transcript.append({"action": {"tool": tool, "args": args, "result": res}})
            messages.append({"role": "assistant", "content": json.dumps(plan)})

        return transcript


@app.command()
def run(
    model: str = typer.Option("gpt-5", help="OpenAI model id"),
    sse_url: str = typer.Option(os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse"), help="MCP SSE endpoint"),
    max_steps: int = typer.Option(12, help="Max tool steps"),
    artifacts_dir: str | None = typer.Option(None, help="Artifacts directory for server trace (set VEI_ARTIFACTS_DIR too)"),
    openai_base_url: str | None = typer.Option(None, help="Override OPENAI_BASE_URL for SDK (OpenAI-compatible)"),
    openai_api_key: str | None = typer.Option(None, help="Override OPENAI_API_KEY for SDK"),
    task: str | None = typer.Option(None, help="High-level goal for the LLM (prefixed as 'Task: ...')"),
    autostart: bool = typer.Option(True, help="Auto-start local VEI SSE server if not reachable"),
) -> None:
    load_dotenv(override=True)
    if not os.getenv("OPENAI_API_KEY"):
        raise typer.BadParameter("OPENAI_API_KEY not set (put it in .env)")
    if artifacts_dir:
        os.environ["VEI_ARTIFACTS_DIR"] = artifacts_dir
    # Ensure SSE server is up
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
    if autostart and not _port_open(host, port):
        env = os.environ.copy()
        env.setdefault("VEI_HOST", host)
        env.setdefault("VEI_PORT", str(port))
        subprocess.Popen(["python", "-m", "vei.router.sse"], env=env)
        for _ in range(20):
            if _port_open(host, port):
                break
            time.sleep(0.1)
    transcript = asyncio.run(
        loop(
            model=model,
            sse_url=sse_url,
            max_steps=max_steps,
            artifacts_dir=artifacts_dir,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            task=task,
        )
    )
    typer.echo(json.dumps(transcript, indent=2))


if __name__ == "__main__":
    app()


