from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import typer
try:  # optional dependency; present when installing extras [llm]
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback when not installed
    def load_dotenv(*args: object, **kwargs: object) -> None:
        return None

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

app = typer.Typer(add_completion=False)


async def _call(session: ClientSession, tool: str, args: dict) -> dict:
    return await session.call_tool(tool, args)


def _ensure_sse_available(sse_url: str, autostart: bool) -> bool:
    def _port_open(host: str, port: int) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((host, port)) == 0
            except Exception:
                return False
    from urllib.parse import urlparse
    parsed = urlparse(sse_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3001
    if _port_open(host, port):
        return True
    if not autostart:
        return False
    env = os.environ.copy()
    env.setdefault("VEI_HOST", host)
    env.setdefault("VEI_PORT", str(port))
    subprocess.Popen(["python", "-m", "vei.router.sse"], env=env)
    # Wait up to ~8 seconds for server to bind
    for _ in range(80):
        if _port_open(host, port):
            return True
        time.sleep(0.1)
    return False


async def _scripted_episode(sse_url: str, max_observes: int = 24) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    async with sse_client(sse_url) as (read, write):
        s = ClientSession(read, write)
        await s.initialize()

        # Minimal, deterministic policy: read -> slack summary -> compose -> observe until drain
        obs = await _call(s, "vei.observe", {})
        transcript.append({"observation": obs})
        res = await _call(s, "browser.read", {})
        transcript.append({"action": {"tool": "browser.read", "args": {}, "result": res}})
        res = await _call(s, "slack.send_message", {"channel": "#procurement", "text": "Summary: budget $3200, citations included."})
        transcript.append({"action": {"tool": "slack.send_message", "args": {"channel": "#procurement"}, "result": res}})
        res = await _call(s, "mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."})
        transcript.append({"action": {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example"}, "result": res}})

        for _ in range(max_observes):
            obs = await _call(s, "vei.observe", {"focus": "mail"})
            transcript.append({"observation": obs})
            pend = obs.get("pending_events", {})
            if pend.get("mail", 0) == 0 and pend.get("slack", 0) == 0:
                break

    return transcript


@app.command()
def run(
    sse_url: str = typer.Option(os.environ.get("VEI_SSE_URL", "http://127.0.0.1:3001/sse"), help="MCP SSE endpoint"),
    artifacts_dir: Path | None = typer.Option(None, help="Artifacts directory for server trace"),
    autostart: bool = typer.Option(True, help="Auto-start local SSE server if not reachable"),
    mode: str = typer.Option("scripted", help="'scripted' (no API key) or 'llm' (requires OPENAI_API_KEY)", show_default=True),
    model: str = typer.Option("gpt-5", help="Model for LLM mode"),
    task: str | None = typer.Option("Research specs, Slack approval < $3200, email vendor.", help="LLM task"),
    max_steps: int = typer.Option(12, help="Max steps for LLM mode"),
    openai_base_url: str | None = typer.Option(None, help="Override OPENAI_BASE_URL"),
    openai_api_key: str | None = typer.Option(None, help="Override OPENAI_API_KEY"),
    score: bool = typer.Option(False, help="Print score summary after transcript"),
) -> None:
    load_dotenv(override=True)
    if artifacts_dir:
        os.environ["VEI_ARTIFACTS_DIR"] = str(artifacts_dir)

    ok = _ensure_sse_available(sse_url, autostart)
    if not ok:
        typer.echo(f"Error: SSE server not reachable at {sse_url}. Use --autostart or start it manually (python -m vei.router.sse).", err=True)
        raise typer.Exit(code=1)

    if mode.strip().lower() == "llm":
        from openai import AsyncOpenAI
        transcript: list[dict[str, Any]] = []
        async def _llm() -> list[dict[str, Any]]:
            async with sse_client(sse_url) as (read, write):
                s = ClientSession(read, write)
                await s.initialize()
                client = AsyncOpenAI(base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"), api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"))
                messages: list[dict] = [{"role": "system", "content": "You control MCP tools. Call vei.observe then choose exactly one tool and JSON args each step."}]
                if task:
                    messages.append({"role": "user", "content": f"Task: {task}"})
                # Simple 1-tool-per-step loop
                for i in range(max_steps):
                    obs = await _call(s, "vei.observe", {})
                    transcript.append({"observation": obs})
                    pend = obs.get("pending_events", {})
                    # Only early-stop after at least one step to allow the model to act
                    if i > 0 and pend.get("mail", 0) == 0 and pend.get("slack", 0) == 0:
                        break
                    menu = obs.get("action_menu", [])
                    menu_text = "\n".join(f"- {m.get('tool')} {json.dumps(m.get('args', m.get('args_schema', {})))}" for m in menu)
                    user = (
                        f"Time: {obs.get('time_ms')}\nFocus: {obs.get('focus')}\nSummary: {obs.get('summary')}\n"
                        f"Pending: {json.dumps(obs.get('pending_events'))}\nAction menu (choose ONE):\n{menu_text}\n"
                        "Reply strictly as JSON {\"tool\": str, \"args\": object}."
                    )
                    messages.append({"role": "user", "content": user})
                    chat = await client.chat.completions.create(model=model, messages=messages, temperature=0)
                    raw = chat.choices[0].message.content or "{}"
                    try:
                        plan = json.loads(raw) if "{" in raw else {"tool": "vei.observe", "args": {}}
                    except Exception:
                        plan = {"tool": "vei.observe", "args": {}}
                    tool = plan.get("tool", "vei.observe")
                    args = plan.get("args", {})
                    res = await _call(s, tool, args)
                    transcript.append({"action": {"tool": tool, "args": args, "result": res}})
                    messages.append({"role": "assistant", "content": json.dumps(plan)})

                    # Auto-drain pending events after key actions to ensure bounded runs
                    if tool in {"mail.compose", "slack.send_message"}:
                        try:
                            # Advance time to deliver scheduled events deterministically
                            await _call(s, "vei.tick", {"dt_ms": 20000})
                            obs2 = await _call(s, "vei.observe", {})
                            transcript.append({"observation": obs2})
                            p2 = obs2.get("pending_events", {})
                            if p2.get("mail", 0) == 0 and p2.get("slack", 0) == 0:
                                break
                        except Exception:
                            ...
                return transcript
        try:
            out = asyncio.run(_llm())
        except Exception as e:
            typer.echo(f"Error running LLM demo: {e}", err=True)
            raise typer.Exit(code=1)
    else:
        try:
            out = asyncio.run(_scripted_episode(sse_url))
        except Exception as e:
            typer.echo(f"Error running scripted demo: {e}", err=True)
            raise typer.Exit(code=1)

    typer.echo(json.dumps(out, indent=2))

    # If we captured artifacts, try to score
    if score:
        try:
            from vei.cli.vei_score import score as score_cmd
            import typer.testing
            if os.environ.get("VEI_ARTIFACTS_DIR"):
                runner = typer.testing.CliRunner()
                result = runner.invoke(score_cmd, ["--artifacts-dir", os.environ["VEI_ARTIFACTS_DIR"]])
                if result.exit_code == 0:
                    typer.echo("\nScore:")
                    typer.echo(result.stdout)
        except Exception:
            ...


if __name__ == "__main__":
    app()


