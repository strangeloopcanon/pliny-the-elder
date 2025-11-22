from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple, List, Iterable
import re
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from ._llm_loop import extract_plan
from vei.llm.providers import plan_once, auto_provider_for_model


_CLAUDE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_tool_name(name: str, seen: set[str]) -> str:
    alias = _CLAUDE_NAME_PATTERN.sub("_", name)
    if not alias:
        alias = "tool"
    alias = alias[:64]
    base = alias
    suffix = 1
    while alias in seen:
        trimmed = base[: max(0, 63 - len(str(suffix)))]
        alias = f"{trimmed}_{suffix}"
        suffix += 1
    seen.add(alias)
    return alias


PREFERRED_ANTHROPIC_TOOLS: List[str] = [
    "vei.observe",
    "vei.tick",
    "browser.read",
    "browser.open",
    "browser.find",
    "browser.click",
    "browser.back",
    "slack.send_message",
    "slack.fetch_thread",
    "mail.list",
    "mail.open",
    "mail.compose",
    "docs.read",
    "docs.search",
    "tickets.list",
    "tickets.get",
]


BASELINE_VISIBLE_TOOLS: List[str] = [
    "vei.observe",
    "vei.tick",
    "vei.act_and_observe",
    "vei.tools.search",
    "vei.state",
    "vei.call",
]


def _select_visible_tools(
    *,
    available: Iterable[str],
    action_menu: Iterable[Dict[str, Any]] | None,
    search_matches: Iterable[str],
    baseline: Iterable[str],
    top_k: int,
) -> List[str]:
    available_list = list(available)
    available_set = {name for name in available_list}
    ordered: List[str] = []

    def _add(name: str) -> None:
        if name and name in available_set and name not in ordered:
            ordered.append(name)

    baseline_set = {name for name in baseline if name in available_set}
    for name in baseline_set:
        _add(name)

    action_tools = {
        str(item.get("tool"))
        for item in (action_menu or [])
        if isinstance(item, dict) and item.get("tool")
    }
    for name in sorted(action_tools):
        _add(name)

    for match in search_matches:
        _add(match)

    for name in available_list:
        _add(name)

    if top_k and top_k > 0:
        required = baseline_set.union(action_tools)
        required_count = sum(1 for name in ordered if name in required)
        limit = max(top_k, required_count)
        return ordered[:limit]
    return ordered


def _build_anthropic_tool_schemas(tools_info: object) -> Tuple[list[dict[str, Any]], Dict[str, str]]:
    schemas: list[dict[str, Any]] = []
    alias_map: Dict[str, str] = {}
    seen_aliases: set[str] = set()
    for tool in getattr(tools_info, "tools", []) or []:
        name = getattr(tool, "name", None)
        if not name or name == "vei.inject":
            continue
        alias = _sanitize_tool_name(name, seen_aliases)
        alias_map[alias] = name
        description = getattr(tool, "description", "") or f"MCP tool {name}"
        schema = None
        for attr in ("input_schema", "inputSchema", "parameters", "schema"):
            candidate = getattr(tool, attr, None)
            if candidate is not None:
                schema = candidate
                break
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump()
        elif hasattr(schema, "dict"):
            schema = schema.dict()  # type: ignore[attr-defined]
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except Exception:
                schema = None
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}, "additionalProperties": True}
        schemas.append({
            "name": alias,
            "description": description,
            "input_schema": schema,
        })
    if len(schemas) > 16:
        tool_names = sorted(alias_map.values())
        tool_list_preview = ", ".join(tool_names[:24])
        if len(tool_names) > 24:
            tool_list_preview += ", ..."
        schemas = [
            {
                "name": "vei_call",
                "description": (
                    "Bridge tool to invoke any MCP function. "
                    "Set args.tool to one of: " + tool_list_preview + ". "
                    "Provide args.args as the JSON argument object."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Name of the MCP tool to invoke"
                        },
                        "args": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "Arguments object for the selected tool"
                        }
                    },
                    "required": ["tool", "args"],
                },
            }
        ]
        alias_map = {}
    return schemas, alias_map


def _filter_anthropic_tools(
    schemas: list[dict[str, Any]] | None,
    alias_map: Dict[str, str] | None,
    allowed_tools: Iterable[str],
) -> Tuple[list[dict[str, Any]] | None, Dict[str, str] | None]:
    if not schemas:
        return None, alias_map
    if not alias_map:
        return schemas, alias_map

    allowed_set = {name for name in allowed_tools}
    reverse_alias = {true: alias for alias, true in alias_map.items()}
    allowed_aliases = {reverse_alias[name] for name in allowed_set if name in reverse_alias}

    filtered = [
        schema
        for schema in schemas
        if schema.get("name") == "vei_call" or schema.get("name") in allowed_aliases
    ]
    if not filtered:
        filtered = [schema for schema in schemas if schema.get("name") == "vei_call"] or schemas[: min(16, len(schemas))]
        allowed_aliases = {schema.get("name") for schema in filtered if schema.get("name") in alias_map}
    trimmed_alias_map = {alias: alias_map[alias] for alias in allowed_aliases}
    return filtered, trimmed_alias_map


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
    tool_top_k: int = 0,
    interactive: bool = False,
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
            anthropic_tool_schemas: list[dict[str, Any]] | None = None
            anthropic_alias_map: Dict[str, str] | None = None
            tool_catalog: Dict[str, Dict[str, Any]] = {}
            try:
                tools_info = await session.list_tools()
                for tool in getattr(tools_info, "tools", []) or []:
                    name = getattr(tool, "name", None)
                    if not name or name == "vei.inject":
                        continue
                    description = getattr(tool, "description", "") or f"MCP tool {name}"
                    tool_catalog[name] = {"description": description}
                for baseline in BASELINE_VISIBLE_TOOLS:
                    tool_catalog.setdefault(baseline, {"description": ""})
                tool_names = sorted(tool_catalog.keys())
                anthropic_tool_schemas, anthropic_alias_map = _build_anthropic_tool_schemas(tools_info)
            except Exception:
                fallback_names = {
                    "vei.observe",
                    "vei.tick",
                    "vei.help",
                    "vei.tools.search",
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
                tool_catalog = {name: {"description": ""} for name in fallback_names}
                for baseline in BASELINE_VISIBLE_TOOLS:
                    tool_catalog.setdefault(baseline, {"description": ""})
                tool_names = sorted(tool_catalog.keys())

            base_prompt = SYSTEM_PROMPT
            if task:
                base_prompt += f"\nTask: {task}"
            transcript: list[dict] = []
            history: list[str] = []

            # One-time catalog hints for common tools to reduce ambiguity
            common_hints: dict[str, dict] = {
                "browser.read": {},
                "browser.find": {"query": "str", "top_k": "int?"},
                "browser.click": {"node_id": "from observation.action_menu"},
                "browser.open": {"url": "https://vweb.local/..."},
                "vei.tick": {"dt_ms": 20000},
                "vei.tools.search": {"query": "keywords", "top_k": tool_top_k or 8},
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

            prev_tool: str | None = None
            last_search_query: str | None = None
            last_search_results: List[str] = []

            for step in range(max_steps):
                obs_raw = await call_mcp_tool(session, "vei.observe", {})
                obs = _normalize_result(obs_raw)

                if interactive:
                    print(f"\n--- Step {step} ---")
                    print(f"Observation: {json.dumps(obs, indent=2)}")
                    while True:
                        import sys
                        print("Press Enter to continue, or 'i' to inject event...", file=sys.stderr)
                        cmd = input("> ").strip()
                        if cmd == 'i':
                            target = input("Target (slack/mail) [slack]: ").strip() or "slack"
                            if target == "slack":
                                text = input("Message text: ").strip()
                                user_id = input("User [cfo]: ").strip() or "cfo"
                                channel = input("Channel [#procurement]: ").strip() or "#procurement"
                                payload = {"channel": channel, "text": text, "user": user_id}
                            elif target == "mail":
                                subj = input("Subject: ").strip()
                                body = input("Body: ").strip()
                                sender = input("From [human@example.com]: ").strip() or "human@example.com"
                                payload = {"from": sender, "subj": subj, "body_text": body}
                            else:
                                print("Unknown target")
                                continue

                            try:
                                await call_mcp_tool(session, "vei.inject", {"target": target, "payload": payload, "dt_ms": 0})
                                print(f"Injected event to {target}.")
                                # Re-observe to capture the effect
                                obs_raw = await call_mcp_tool(session, "vei.observe", {})
                                obs = _normalize_result(obs_raw)
                                print(f"Updated Observation: {json.dumps(obs, indent=2)}")
                            except Exception as e:
                                print(f"Injection failed: {e}")
                        else:
                            break

                transcript.append({"observation": obs})
                history.append(f"observation {step}: {json.dumps(obs)}")
                action_menu = obs.get("action_menu") if isinstance(obs, dict) else None

                search_matches: List[str] = []
                if tool_top_k and tool_top_k > 0:
                    query_parts: List[str] = []
                    if task:
                        query_parts.append(task)
                    summary = obs.get("summary") if isinstance(obs, dict) else None
                    if isinstance(summary, str):
                        query_parts.append(summary)
                    focus = obs.get("focus") if isinstance(obs, dict) else None
                    if isinstance(focus, str):
                        query_parts.append(focus)
                    menu_tools: List[str] = []
                    if isinstance(action_menu, list):
                        for item in action_menu:
                            if isinstance(item, dict) and item.get("tool"):
                                menu_tools.append(str(item.get("tool")))
                            if len(menu_tools) >= 4:
                                break
                    if menu_tools:
                        query_parts.extend(menu_tools)
                    query = " ".join(part for part in query_parts if part).strip()
                    if not query and prev_tool:
                        query = prev_tool

                    if query:
                        if query != last_search_query:
                            try:
                                search_resp = await call_mcp_tool(
                                    session,
                                    "vei.tools.search",
                                    {"query": query, "top_k": tool_top_k},
                                )
                                results = search_resp.get("results", []) if isinstance(search_resp, dict) else []
                                search_matches = [
                                    str(item.get("name"))
                                    for item in results
                                    if isinstance(item, dict) and item.get("name") in tool_catalog
                                ]
                                last_search_query = query
                                last_search_results = search_matches[:]
                                transcript.append({"tool_search": {"query": query, "results": search_matches}})
                            except Exception:
                                search_matches = []
                                last_search_query = query
                                last_search_results = []
                        else:
                            search_matches = last_search_results[:]

                visible_tools = _select_visible_tools(
                    available=tool_names,
                    action_menu=action_menu if isinstance(action_menu, list) else None,
                    search_matches=search_matches,
                    baseline=BASELINE_VISIBLE_TOOLS,
                    top_k=tool_top_k,
                )

                catalog_lines = []
                for name in visible_tools:
                    desc = tool_catalog.get(name, {}).get("description", "")
                    if desc:
                        catalog_lines.append(f"- {name}: {desc}")
                    else:
                        catalog_lines.append(f"- {name}")
                catalog_text = "\n".join(catalog_lines)
                hints_lines = [f"- {k} {json.dumps(v)}" for k, v in common_hints.items() if k in visible_tools]
                hints_text = "\n".join(hints_lines)

                # Open schema (no gating). We present the tool subset plus allow vei.call for escapes.
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

                provider_schemas = anthropic_tool_schemas
                provider_alias_map = anthropic_alias_map
                if eff_provider == "anthropic":
                    provider_schemas, provider_alias_map = _filter_anthropic_tools(
                        anthropic_tool_schemas,
                        anthropic_alias_map,
                        visible_tools,
                    )
                try:
                    plan = await plan_once(
                        provider=eff_provider,
                        model=model,
                        system=base_prompt,
                        user=user,
                        plan_schema=plan_schema,
                        timeout_s=240,
                        openai_base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
                        openai_api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
                        anthropic_api_key=anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"),
                        google_api_key=google_api_key or os.environ.get("GOOGLE_API_KEY"),
                        openrouter_api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"),
                        tool_schemas=provider_schemas if eff_provider == "anthropic" else None,
                        alias_map=provider_alias_map if eff_provider == "anthropic" else None,
                    )
                except Exception as e:
                    plan_error = f"Provider error: {type(e).__name__}: {str(e)}"
                    transcript.append({"plan_error": plan_error})
                    raise  # FAIL FAST - no masking

                if eff_provider == "anthropic" and provider_alias_map:
                    tool_alias = plan.get("tool")
                    if tool_alias in provider_alias_map:
                        plan["tool"] = provider_alias_map[tool_alias]

                tool = str(plan.get("tool", "vei.observe"))
                args = plan.get("args", {}) if isinstance(plan.get("args"), dict) else {}

                # If model returns a no-op after the first step, retry once with a stronger prompt.
                if tool == "vei.observe" and prev_tool is not None:
                    transcript.append({"action": {"tool": tool, "args": args, "retried": True, "original_plan": plan}})

                    retry_user_prompt = user + (
                        "\n\nCRITICAL: You returned 'vei.observe' when an action was required. You MUST choose a "
                        "different, non-observe tool to make progress. What is the next concrete action?"
                    )
                    try:
                        plan = await plan_once(
                            provider=eff_provider,
                            model=model,
                            system=base_prompt,
                            user=retry_user_prompt,
                            plan_schema=plan_schema,
                            timeout_s=240,
                            openai_base_url=openai_base_url or os.environ.get("OPENAI_BASE_URL"),
                            openai_api_key=openai_api_key or os.environ.get("OPENAI_API_KEY"),
                            anthropic_api_key=anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"),
                            google_api_key=google_api_key or os.environ.get("GOOGLE_API_KEY"),
                            openrouter_api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"),
                            tool_schemas=provider_schemas if eff_provider == "anthropic" else None,
                            alias_map=provider_alias_map if eff_provider == "anthropic" else None,
                        )
                        if eff_provider == "anthropic" and provider_alias_map:
                            alias = plan.get("tool")
                            if alias in provider_alias_map:
                                plan["tool"] = provider_alias_map[alias]
                        tool = str(plan.get("tool", "vei.observe"))
                        args = plan.get("args", {}) if isinstance(plan.get("args"), dict) else {}
                    except Exception as e:
                        plan_error = f"Provider error on retry: {type(e).__name__}: {str(e)}"
                        transcript.append({"plan_error": plan_error})
                        raise

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
    tool_top_k: int = typer.Option(
        0,
        help="If >0, limit prompt-visible tools to top-K retrieved via vei.tools.search (baseline tools always included).",
    ),
    interactive: bool = typer.Option(False, help="Run in interactive mode to allow manual event injection."),
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
            tool_top_k=tool_top_k,
            interactive=interactive,
        )
    )
    typer.echo(json.dumps(transcript, indent=2))


if __name__ == "__main__":
    app()
