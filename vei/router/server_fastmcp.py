from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import server as fserver
from pydantic import BaseModel, Field

from .core import Router, MCPError


class SlackOpenArgs(BaseModel):
    channel: str


class SlackSendArgs(BaseModel):
    channel: str
    text: str
    thread_ts: str | None = None


class SlackReactArgs(BaseModel):
    channel: str
    ts: str
    emoji: str


class SlackFetchThreadArgs(BaseModel):
    channel: str
    thread_ts: str


class MailListArgs(BaseModel):
    folder: str = "INBOX"


class MailOpenArgs(BaseModel):
    id: str


class MailComposeArgs(BaseModel):
    to: str
    subj: str
    body_text: str


class MailReplyArgs(BaseModel):
    id: str
    body_text: str


class BrowserOpenArgs(BaseModel):
    url: str


class BrowserFindArgs(BaseModel):
    query: str
    top_k: int = 10


class BrowserClickArgs(BaseModel):
    node_id: str


class BrowserTypeArgs(BaseModel):
    node_id: str
    text: str


class BrowserSubmitArgs(BaseModel):
    form_id: str


class ObserveArgs(BaseModel):
    focus: str | None = None


class ResetArgs(BaseModel):
    seed: int | None = None


class ActAndObserveArgs(BaseModel):
    tool: str
    # Avoid shared mutable defaults across requests
    args: dict[str, Any] = Field(default_factory=dict)


class TickArgs(BaseModel):
    dt_ms: int = 1000


class _RouterHolder:
    def __init__(self, router: Router):
        self.router = router


def create_mcp_server(router: Router, host: str | None = None, port: int | None = None, mount_path: str = "/") -> fserver.FastMCP:
    # Read host/port from args or env (defaults)
    if host is None:
        host = os.environ.get("VEI_HOST", "127.0.0.1")
    if port is None:
        try:
            port = int(os.environ.get("VEI_PORT", "3001"))
        except ValueError:
            port = 3001

    # Honor logging and debug via env so diagnostics show up
    log_level = os.environ.get("FASTMCP_LOG_LEVEL", "INFO").upper()
    debug_flag = os.environ.get("FASTMCP_DEBUG", "0") in {"1", "true", "TRUE", "yes", "on"}

    # Relax transport security for local dev if explicitly requested
    ts = None
    if os.environ.get("FASTMCP_DISABLE_SECURITY") in {"1", "true", "TRUE", "yes", "on"}:
        try:
            from mcp.server.fastmcp.server import TransportSecuritySettings  # type: ignore
            ts = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        except Exception:
            ts = None

    srv = fserver.FastMCP(
        name="VEI Router",
        instructions="Virtual Enterprise Internet — synthetic MCP world",
        host=host,
        port=port,
        mount_path=mount_path,
        log_level=log_level,  # ensure FastMCP logging reflects env
        debug=debug_flag,
        transport_security=ts,
    )
    holder = _RouterHolder(router)

    # Utility to access current router
    def R() -> Router:
        return holder.router

    @srv.tool(name="slack.list_channels", description="List Slack channels")
    def slack_list_channels() -> list[str]:
        return R().call_and_step("slack.list_channels", {})  # type: ignore[return-value]

    @srv.tool(name="slack.open_channel", description="Open a Slack channel")
    def slack_open_channel(channel: str) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.open_channel", {"channel": channel})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.send_message", description="Send a Slack message")
    def slack_send_message(channel: str, text: str, thread_ts: str | None = None) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.send_message", {"channel": channel, "text": text, "thread_ts": thread_ts})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.react", description="React to a message")
    def slack_react(channel: str, ts: str, emoji: str) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.react", {"channel": channel, "ts": ts, "emoji": emoji})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.fetch_thread", description="Fetch a thread")
    def slack_fetch_thread(channel: str, thread_ts: str) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.fetch_thread", {"channel": channel, "thread_ts": thread_ts})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="mail.list", description="List mail folder")
    def mail_list(folder: str = "INBOX") -> list[dict[str, Any]]:
        return R().call_and_step("mail.list", {"folder": folder})  # type: ignore[return-value]

    @srv.tool(name="mail.open", description="Open a message")
    def mail_open(id: str) -> dict[str, Any]:
        try:
            return R().call_and_step("mail.open", {"id": id})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="mail.compose", description="Compose a message")
    def mail_compose(to: str, subj: str, body_text: str) -> dict[str, Any]:
        return R().call_and_step("mail.compose", {"to": to, "subj": subj, "body_text": body_text})

    @srv.tool(name="mail.reply", description="Reply to a message")
    def mail_reply(id: str, body_text: str) -> dict[str, Any]:
        try:
            return R().call_and_step("mail.reply", {"id": id, "body_text": body_text})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="browser.open", description="Open a URL")
    def browser_open(url: str) -> dict[str, Any]:
        return R().call_and_step("browser.open", {"url": url})

    @srv.tool(name="browser.find", description="Find visible affordances")
    def browser_find(query: str, top_k: int = 10) -> dict[str, Any]:
        return R().call_and_step("browser.find", {"query": query, "top_k": top_k})

    @srv.tool(name="browser.click", description="Click an affordance")
    def browser_click(node_id: str) -> dict[str, Any]:
        try:
            return R().call_and_step("browser.click", {"node_id": node_id})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="browser.type", description="Type into a field")
    def browser_type(node_id: str, text: str) -> dict[str, Any]:
        return R().call_and_step("browser.type", {"node_id": node_id, "text": text})

    @srv.tool(name="browser.submit", description="Submit a form")
    def browser_submit(form_id: str) -> dict[str, Any]:
        return R().call_and_step("browser.submit", {"form_id": form_id})

    @srv.tool(name="browser.read", description="Read current page")
    def browser_read() -> dict[str, Any]:
        return R().call_and_step("browser.read", {})

    @srv.tool(name="browser.back", description="Navigate back")
    def browser_back() -> dict[str, Any]:
        return R().call_and_step("browser.back", {})

    @srv.tool(name="vei.observe", description="Get current observation summary + action menu")
    def vei_observe(focus: str | None = None) -> dict[str, Any]:
        return R().observe(focus_hint=focus).model_dump()

    @srv.tool(name="vei.ping", description="Health check and current logical time")
    def vei_ping() -> dict[str, Any]:
        return {"ok": True, "time_ms": R().bus.clock_ms}

    @srv.tool(name="vei.reset", description="Reset the simulation deterministically (optionally with a new seed)")
    def vei_reset(seed: int | None = None) -> dict[str, Any]:
        old = R()
        new_seed = int(seed) if seed is not None else int(os.environ.get("VEI_SEED", "42042"))
        # Preserve scenario and artifacts configuration so the environment stays consistent for the session
        new_router = Router(seed=new_seed, artifacts_dir=old.trace.out_dir, scenario=old.scenario)
        holder.router = new_router
        return {"ok": True, "seed": new_seed, "time_ms": new_router.bus.clock_ms}

    @srv.tool(name="vei.act_and_observe", description="Execute a tool and return its result and a post-action observation")
    def vei_act_and_observe(tool: str, args: dict[str, Any] = Field(default_factory=dict)) -> dict[str, Any]:
        data = R().act_and_observe(tool, args)
        return data

    @srv.tool(name="vei.tick", description="Advance logical time by dt_ms and deliver due events")
    def vei_tick(dt_ms: int = 1000) -> dict[str, Any]:
        return R().tick(dt_ms)

    @srv.tool(name="vei.pending", description="Return pending event counts without advancing time")
    def vei_pending() -> dict[str, int]:
        return R().pending()

    @srv.tool(name="vei.help", description="Usage help: how to interact via MCP and example actions")
    def vei_help() -> dict[str, Any]:
        return {
            "instructions": (
                "Use MCP tools to interact with the VEI environment. Typical loop: "
                "(1) call vei.observe {} to obtain an observation with an action_menu and pending_events; "
                "(2) choose exactly one tool to call (often from action_menu) then call vei.observe {}; "
                "or simply call vei.act_and_observe {tool,args} to do both in one step; (3) repeat."
            ),
            "tools": [
                {"tool": "vei.observe", "args": {"focus": "browser|slack|mail?"}},
                {"tool": "vei.act_and_observe", "args": {"tool": "str", "args": "object"}},
                {"tool": "vei.tick", "args": {"dt_ms": "int?"}},
                {"tool": "vei.pending", "args": {}},
                {"tool": "vei.reset", "args": {"seed": "int?"}},
                {"tool": "browser.read", "args": {}},
                {"tool": "browser.find", "args": {"query": "str", "top_k": "int?"}},
                {"tool": "browser.click", "args": {"node_id": "str"}},
                {"tool": "browser.open", "args": {"url": "str"}},
                {"tool": "browser.type", "args": {"node_id": "str", "text": "str"}},
                {"tool": "browser.submit", "args": {"form_id": "str"}},
                {"tool": "browser.back", "args": {}},
                {"tool": "slack.list_channels", "args": {}},
                {"tool": "slack.open_channel", "args": {"channel": "str"}},
                {"tool": "slack.send_message", "args": {"channel": "str", "text": "str", "thread_ts": "str?"}},
                {"tool": "slack.react", "args": {"channel": "str", "ts": "str", "emoji": "str"}},
                {"tool": "slack.fetch_thread", "args": {"channel": "str", "thread_ts": "str"}},
                {"tool": "mail.list", "args": {"folder": "str?"}},
                {"tool": "mail.open", "args": {"id": "str"}},
                {"tool": "mail.compose", "args": {"to": "str", "subj": "str", "body_text": "str"}},
                {"tool": "mail.reply", "args": {"id": "str", "body_text": "str"}},
            ],
            "examples": [
                {"tool": "vei.observe", "args": {}},
                {"tool": "browser.read", "args": {}},
                {"tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Summary: budget $3200, citations included."}},
                {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."}},
                {"tool": "vei.ping", "args": {}},
                {"tool": "vei.reset", "args": {"seed": 42042}},
                {"tool": "vei.act_and_observe", "args": {"tool": "browser.read", "args": {}}},
            ],
        }

    return srv
