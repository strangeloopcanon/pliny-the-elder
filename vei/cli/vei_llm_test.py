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
from ._llm_loop import extract_plan
from vei.llm.providers import plan_once, auto_provider_for_model


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
    "You are an MCP agent operating in a synthetic enterprise environment with deterministic tool twins. "
    "Environment summary: Browser pages contain product info for citations; Slack approvals must include a budget amount and (ideally) a link; emailing a vendor via mail.compose triggers a vendor reply containing price and ETA; time advances via deterministic steps and vei.tick. "
    "Scoring emphasizes: final task success (parsed vendor email with price+ETA), subgoals (browser.read for citation, Slack approval, outbound email), and efficiency (fewer steps). "
    "Planner rules: one tool per step. Start with a single vei.observe to inspect state. AFTER THAT, you MUST select a non-observe action that progresses the goal. Do not return vei.observe twice in a row. Prefer concrete actions (browser.read, slack.send_message with budget+URL, mail.compose, mail.list/open, vei.tick). "
    "Examples (JSON only): "
    "Step 1 → {\"tool\": \"browser.read\", \"args\": {}} "
    "Step 2 → {\"tool\": \"slack.send_message\", \"args\": {\"channel\": \"#procurement\", \"text\": \"Budget $3200. Link: https://vweb.local/pdp/macrobook-pro-16\"}} "
    "Step 3 → {\"tool\": \"mail.compose\", \"args\": {\"to\": \"sales@macrocompute.example\", \"subj\": \"Quote request\", \"body_text\": \"Please send latest price and ETA.\"}} "
    "Step 4 → {\"tool\": \"vei.tick\", \"args\": {\"dt_ms\": 20000}} "
    "Always reply with a single JSON object of the form {\"tool\": string, \"args\": object}."
)


async def call_mcp_tool(session: ClientSession, tool: str, args: dict) -> dict:
    return await session.call_tool(tool, args)


async def run_episode(
    model: str,
    sse_url: str,  # kept for signature compatibility; ignored in stdio mode
    max_steps: int = 12,
    provider: str | None = None,
    engine: str | None = None,  # reserved for future (simonw/llm) path
    openai_base_url: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    google_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    task: str | None = None,
    dataset_path: str | None = None,
    artifacts_dir: str | None = None,
) -> list[dict]:
    # stdio-only transport
    py = os.environ.get("PYTHON", None) or (sys.executable if 'sys' in globals() else None)
    if not py:
        import sys as _sys
        py = _sys.executable or "python3"
    env = {**os.environ, "VEI_DISABLE_AUTOSTART": "1"}
    if dataset_path:
        env["VEI_DATASET"] = dataset_path
    if artifacts_dir:
        env["VEI_ARTIFACTS_DIR"] = artifacts_dir
    params = StdioServerParameters(command=py, args=["-m", "vei.router"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Enumerate full tool catalog so the model can "see" the environment
            try:
                tools_info = await session.list_tools()
                tool_names = sorted({t.name for t in tools_info.tools})  # type: ignore[attr-defined]
            except Exception:
                tool_names = sorted(
                    {
                        "vei.observe",
                        "vei.tick",
                        "vei.help",
                        "browser.read",
                        "browser.find",
                        "browser.open",
                        "browser.click",
                        "browser.back",
                        "slack.send_message",
                        "mail.compose",
                        "mail.list",
                        "mail.open",
                        "mail.reply",
                    }
                )

            base_prompt = SYSTEM_PROMPT
            if task:
                base_prompt += f"\nTask: {task}"
            transcript: list[dict] = []
            history: list[str] = []

            # One-time catalog blurb and basic arg hints for common tools to reduce ambiguity
            catalog_text = "\n".join(f"- {n}" for n in tool_names)
            common_hints: dict[str, dict] = {
                "browser.read": {},
                "browser.find": {"query": "str", "top_k": "int?"},
                "browser.click": {"node_id": "from observation.action_menu"},
                "browser.open": {"url": "https://vweb.local/..."},
                "vei.tick": {"dt_ms": 20000},
                "slack.send_message": {
                    "channel": "#procurement",
                    "text": "Budget $3200. Link: https://vweb.local/pdp/macrobook-pro-16",
                },
                "mail.compose": {
                    "to": "sales@macrocompute.example",
                    "subj": "Quote request",
                    "body_text": "Please send latest price and ETA.",
                },
                "mail.list": {},
                "mail.open": {"id": "m1"},
                "mail.reply": {"id": "m1", "body_text": "Thanks; confirming price and ETA."},
            }
            hints_lines = [f"- {k} {json.dumps(v)}" for k, v in common_hints.items() if k in tool_names]
            hints_text = "\n".join(hints_lines)

            prev_tool: str | None = None
            for step in range(max_steps):
                obs_raw = await call_mcp_tool(session, "vei.observe", {})
                obs = _normalize_result(obs_raw)
                transcript.append({"observation": obs})
                history.append(f"observation {step}: {json.dumps(obs)}")
                # Open schema (no gating). We present the full tool catalog in the prompt instead of enumerating here.
                plan_schema = {
                    "name": "vei.plan.schema",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["tool", "args"],
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                        },
                    },
                }
                context_block = "\n".join(history[-6:])
                user = (
                    ("Goal:\n" + (task or "Complete procurement with citations, approval, and vendor email."))
                    + "\n\nTools available (you may use any):\n" + catalog_text
                    + ("\n\nCommon tool arg hints:\n" + hints_text if hints_text else "")
                    + "\n\nObservation:\n" + json.dumps(obs)
                    + "\n\nConsidering this, what is the single next task you should do to accomplish the goal? "
                      "Choose exactly one tool and args that best advances the goal. "
                      "Do not choose 'vei.observe' again unless new information appeared or you must change focus."
                )
                if context_block:
                    user = f"Context:\n{context_block}\n\n{user}"
                # Call selected provider to get plan (JSON with {tool, args})
                eff_provider = auto_provider_for_model(model, (provider or "").strip().lower() or None)
                plan: dict
                plan_error: str | None = None
                try:
                    plan = await plan_once(
                        provider=eff_provider,
                        model=model,
                        system=base_prompt,
                        user=user,
                        plan_schema=plan_schema,
                        timeout_s=30,
                        openai_base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
                        openai_api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
                        anthropic_api_key=anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"),
                        google_api_key=google_api_key or os.environ.get("GOOGLE_API_KEY"),
                        openrouter_api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"),
                    )
                except Exception as e:
                    plan_error = f"Provider error: {type(e).__name__}: {str(e)}"
                    transcript.append({"plan_error": plan_error})
                    raise  # FAIL FAST - no masking
                tool = str(plan.get("tool", "vei.observe"))
                args = plan.get("args", {}) if isinstance(plan.get("args"), dict) else {}
                action_record = {"tool": tool, "args": args}
                if tool == "vei.observe":
                    res_raw = await call_mcp_tool(session, tool, args)
                    res = _normalize_result(res_raw)
                    action_record["result"] = res
                    transcript.append({"action": action_record})
                    history.append(f"action {step}: {json.dumps(action_record)}")
                else:
                    # Execute action and return post-action observation atomically
                    try:
                        ao_raw = await call_mcp_tool(session, "vei.act_and_observe", {"tool": tool, "args": args})
                        ao = _normalize_result(ao_raw)
                        res = ao.get("result", ao)
                        obs2 = ao.get("observation")
                    except Exception as e:
                        res = {"error": str(e)}
                        obs2 = None
                    action_record["result"] = res
                    transcript.append({"action": action_record})
                    history.append(f"action {step}: {json.dumps(action_record)}")
                    if isinstance(obs2, dict):
                        transcript.append({"observation": obs2})
                        history.append(f"observation {step}.1: {json.dumps(obs2)}")

                    # Auto-drain pending events after key actions to keep episodes bounded
                    if tool in {"mail.compose", "slack.send_message"}:
                        try:
                            await call_mcp_tool(session, "vei.tick", {"dt_ms": 20000})
                            obs_raw2 = await call_mcp_tool(session, "vei.observe", {})
                            obs2b = _normalize_result(obs_raw2)
                            transcript.append({"observation": obs2b})
                            history.append(f"observation {step}.tick: {json.dumps(obs2b)}")
                        except Exception:
                            ...
                prev_tool = tool

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
    model: str = typer.Option("gpt-5", help="Model id"),
    provider: str = typer.Option("openai", help="Provider: openai|anthropic|google|openrouter|auto"),
    engine: str = typer.Option("sdk", help="Backend engine: sdk (default). 'llm' reserved."),
    openai_base_url: str | None = typer.Option(None, help="Override OPENAI_BASE_URL for SDK (OpenAI-compatible)"),
    openai_api_key: str | None = typer.Option(None, help="Override OPENAI_API_KEY for SDK"),
    anthropic_api_key: str | None = typer.Option(None, help="Override ANTHROPIC_API_KEY for SDK"),
    google_api_key: str | None = typer.Option(None, help="Override GOOGLE_API_KEY for SDK"),
    openrouter_api_key: str | None = typer.Option(None, help="Override OPENROUTER_API_KEY for SDK"),
    max_steps: int = typer.Option(12, help="Max tool steps"),
    task: str | None = typer.Option(None, help="High-level goal for the LLM (prefixed as 'Task: ...')"),
    dataset: Path | None = typer.Option(None, help="Optional dataset JSON to prime replay"),
    artifacts: Path | None = typer.Option(None, help="Optional artifacts directory for traces"),
) -> None:
    load_dotenv(override=True)
    eff_provider = auto_provider_for_model(model, provider)
    if eff_provider == "openai" and not (openai_api_key or os.getenv("OPENAI_API_KEY")):
        raise typer.BadParameter("OPENAI_API_KEY not set (provide --openai-api-key or put it in .env)")
    if eff_provider == "anthropic" and not (anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")):
        raise typer.BadParameter("ANTHROPIC_API_KEY not set (provide --anthropic-api-key or put it in .env)")
    if eff_provider == "google" and not (
        google_api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    ):
        raise typer.BadParameter(
            "Google API key not set (provide --google-api-key or set GOOGLE_API_KEY/GEMINI_API_KEY in .env)"
        )
    if eff_provider == "openrouter" and not (openrouter_api_key or os.getenv("OPENROUTER_API_KEY")):
        raise typer.BadParameter("OPENROUTER_API_KEY not set (provide --openrouter-api-key or put it in .env)")
    transcript = asyncio.run(
        run_episode(
            model=model,
            sse_url="",  # unused in stdio mode
            max_steps=max_steps,
            provider=provider,
            engine=engine,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            google_api_key=google_api_key,
            openrouter_api_key=openrouter_api_key,
            task=task,
            dataset_path=str(dataset) if dataset else None,
            artifacts_dir=str(artifacts) if artifacts else None,
        )
    )
    typer.echo(json.dumps(transcript, indent=2))


if __name__ == "__main__":
    app()
