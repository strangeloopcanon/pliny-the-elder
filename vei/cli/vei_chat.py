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
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import AsyncOpenAI
from ._llm_loop import extract_plan as _extract_plan


app = typer.Typer(add_completion=False)


SYSTEM_PROMPT = (
    "You are an assistant controlling tools via MCP in a synthetic enterprise world. "
    "Each step: first call 'vei.observe' to see the action_menu, then pick exactly one tool to call. "
    "Return STRICTLY a JSON object with fields {\"tool\": str, \"args\": object}."
)


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

async def call_mcp_tool(session: ClientSession, tool: str, args: dict) -> dict:
    r = await session.call_tool(tool, args)
    return _normalize_result(r)


def extract_plan(raw: str) -> dict[str, Any]:  # Backward shim; delegate to helper with default tool
    return _extract_plan(raw, default_tool="vei.observe")


async def loop(
    model: str,
    transport: str,
    sse_url: str,
    max_steps: int,
    artifacts_dir: str | None,
    openai_base_url: str | None,
    openai_api_key: str | None,
    task: str | None,
    timeout_s: int,
    ) -> list[dict[str, Any]]:
    transport = (transport or "stdio").strip().lower()
    if transport == "stdio":
        import sys as _sys
        env = os.environ.copy()
        # Keep the child stdio server deterministic and quiet (no background SSE)
        env["VEI_DISABLE_AUTOSTART"] = "1"
        env.setdefault("PYTHONUNBUFFERED", "1")
        # Propagate artifacts/scenario if provided so traces are written
        for key in (
            "VEI_ARTIFACTS_DIR",
            "VEI_SCENARIO",
            "VEI_SCENARIO_CONFIG",
            "VEI_SCENARIO_RANDOM",
        ):
            if os.environ.get(key):
                env[key] = os.environ[key]
        params = StdioServerParameters(command=_sys.executable or "python3", args=["-m", "vei.router"], env=env)
        ctx = stdio_client(params, errlog=_sys.stderr)
    else:
        ctx = sse_client(sse_url)

    async with ctx as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

        client = AsyncOpenAI(
            base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
            api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
        )
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if task:
            messages.append({"role": "user", "content": f"Task: {task}"})
        transcript: list[dict[str, Any]] = []
        run_id = os.environ.get("VEI_RUN_ID") or str(int(asyncio.get_running_loop().time() * 1000))

        # Show help to the model
        try:
            help_obj = await call_mcp_tool(session, "vei.help", {})
            transcript.append({"help": help_obj})
        except Exception:
            ...

        for _ in range(max_steps):
            obs = await call_mcp_tool(session, "vei.observe", {})
            transcript.append({"observation": obs, "meta": {"run_id": run_id, "step": _, "time_ms": obs.get("time_ms")}})
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

            try:
                chat = await asyncio.wait_for(
                    client.chat.completions.create(model=model, messages=messages),
                    timeout=timeout_s,
                )
                content = chat.choices[0].message.content or "{}"
            except asyncio.TimeoutError:
                transcript.append({"error": {"type": "llm_timeout", "timeout_s": timeout_s}})
                break
            plan = extract_plan(content)
            transcript.append({"llm_plan": {"raw": content, "parsed": plan}, "meta": {"run_id": run_id, "step": _, "time_ms": obs.get("time_ms")}})

            tool = plan.get("tool", "vei.observe")
            args = plan.get("args", {})
            res = await call_mcp_tool(session, tool, args)
            transcript.append({"action": {"tool": tool, "args": args, "result": res}, "meta": {"run_id": run_id, "step": _, "time_ms": obs.get("time_ms")}})
            messages.append({"role": "assistant", "content": json.dumps(plan)})
            # Auto-drain after key actions to ensure bounded runs
            if tool in {"mail.compose", "slack.send_message"}:
                try:
                    await call_mcp_tool(session, "vei.tick", {"dt_ms": 20000})
                    obs2 = await call_mcp_tool(session, "vei.observe", {})
                    transcript.append({"observation": obs2, "meta": {"run_id": run_id, "step": _, "time_ms": obs2.get("time_ms"), "autodrain": True}})
                except Exception:
                    ...

        return transcript


@app.command()
def run(
    model: str = typer.Option("gpt-5", help="OpenAI model id"),
    transport: str = typer.Option("stdio", help="Transport: sse or stdio"),
    sse_url: str = typer.Option(os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse"), help="MCP SSE endpoint"),
    max_steps: int = typer.Option(12, help="Max tool steps"),
    artifacts_dir: str | None = typer.Option(None, help="Artifacts directory for server trace (set VEI_ARTIFACTS_DIR too)"),
    openai_base_url: str | None = typer.Option(None, help="Override OPENAI_BASE_URL for SDK (OpenAI-compatible)"),
    openai_api_key: str | None = typer.Option(None, help="Override OPENAI_API_KEY for SDK"),
    task: str | None = typer.Option(None, help="High-level goal for the LLM (prefixed as 'Task: ...')"),
    autostart: bool = typer.Option(True, help="Auto-start local VEI SSE server if not reachable"),
    timeout_s: int = typer.Option(45, help="Per-LLM-call timeout seconds"),
    transcript_out: str | None = typer.Option(None, help="Save transcript JSON to file"),
) -> None:
    load_dotenv(override=True)
    if not os.getenv("OPENAI_API_KEY"):
        raise typer.BadParameter("OPENAI_API_KEY not set (put it in .env)")
    if artifacts_dir:
        os.environ["VEI_ARTIFACTS_DIR"] = artifacts_dir
    # Ensure SSE server is up when using SSE
    def _port_open(host: str, port: int) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((host, port)) == 0
            except Exception:
                return False
    if transport.strip().lower() == "sse":
        parsed = urlparse(sse_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3001
        if autostart and not _port_open(host, port):
            env = os.environ.copy()
            env.setdefault("VEI_HOST", host)
            env.setdefault("VEI_PORT", str(port))
            import sys as _sys
            subprocess.Popen([_sys.executable or "python3", "-m", "vei.router.sse"], env=env)
            for _ in range(20):
                if _port_open(host, port):
                    break
                time.sleep(0.1)
    transcript = asyncio.run(
        loop(
            model=model,
            transport=transport,
            sse_url=sse_url,
            max_steps=max_steps,
            artifacts_dir=artifacts_dir,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            task=task,
            timeout_s=timeout_s,
        )
    )
    data = json.dumps(transcript, indent=2)
    if transcript_out:
        try:
            with open(transcript_out, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception:
            typer.echo(data)
    else:
        typer.echo(data)


if __name__ == "__main__":
    app()
