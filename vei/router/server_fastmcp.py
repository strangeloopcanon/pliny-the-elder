from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import server as fserver
from pydantic import BaseModel

from .core import Router, MCPError
from vei.world.scenario import Scenario


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

    srv = fserver.FastMCP(
        name="VEI Router",
        instructions="Virtual Enterprise Internet — synthetic MCP world",
        host=host,
        port=port,
        mount_path=mount_path,
    )
    holder = _RouterHolder(router)

    # Utility to access current router
    def R() -> Router:
        return holder.router

    @srv.tool(name="slack.list_channels", description="List Slack channels")
    def slack_list_channels() -> list[str]:
        return R().call_and_step("slack.list_channels", {})  # type: ignore[return-value]

    @srv.tool(name="slack.open_channel", description="Open a Slack channel")
    def slack_open_channel(args: SlackOpenArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.open_channel", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.send_message", description="Send a Slack message")
    def slack_send_message(args: SlackSendArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.send_message", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.react", description="React to a message")
    def slack_react(args: SlackReactArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.react", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="slack.fetch_thread", description="Fetch a thread")
    def slack_fetch_thread(args: SlackFetchThreadArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("slack.fetch_thread", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="mail.list", description="List mail folder")
    def mail_list(args: MailListArgs) -> list[dict[str, Any]]:
        return R().call_and_step("mail.list", args.model_dump())  # type: ignore[return-value]

    @srv.tool(name="mail.open", description="Open a message")
    def mail_open(args: MailOpenArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("mail.open", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="mail.compose", description="Compose a message")
    def mail_compose(args: MailComposeArgs) -> dict[str, Any]:
        return R().call_and_step("mail.compose", args.model_dump())

    @srv.tool(name="mail.reply", description="Reply to a message")
    def mail_reply(args: MailReplyArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("mail.reply", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="browser.open", description="Open a URL")
    def browser_open(args: BrowserOpenArgs) -> dict[str, Any]:
        return R().call_and_step("browser.open", args.model_dump())

    @srv.tool(name="browser.find", description="Find visible affordances")
    def browser_find(args: BrowserFindArgs) -> dict[str, Any]:
        return R().call_and_step("browser.find", args.model_dump())

    @srv.tool(name="browser.click", description="Click an affordance")
    def browser_click(args: BrowserClickArgs) -> dict[str, Any]:
        try:
            return R().call_and_step("browser.click", args.model_dump())
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="browser.type", description="Type into a field")
    def browser_type(args: BrowserTypeArgs) -> dict[str, Any]:
        return R().call_and_step("browser.type", args.model_dump())

    @srv.tool(name="browser.submit", description="Submit a form")
    def browser_submit(args: BrowserSubmitArgs) -> dict[str, Any]:
        return R().call_and_step("browser.submit", args.model_dump())

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
        # Preserve scenario and artifacts configuration
        new_router = Router(seed=new_seed, artifacts_dir=old.trace.out_dir, scenario=old.scenario)
        holder.router = new_router
        return {"ok": True, "seed": new_seed, "time_ms": new_router.bus.clock_ms}

    class ActAndObserveArgs(BaseModel):
        tool: str
        args: dict[str, Any] = {}

    @srv.tool(name="vei.act_and_observe", description="Execute a tool and return its result and a post-action observation")
    def vei_act_and_observe(args: ActAndObserveArgs) -> dict[str, Any]:
        data = R().act_and_observe(args.tool, args.args)
        return data

    class TickArgs(BaseModel):
        dt_ms: int = 1000

    @srv.tool(name="vei.tick", description="Advance logical time by dt_ms and deliver due events")
    def vei_tick(args: TickArgs) -> dict[str, Any]:
        return R().tick(args.dt_ms)

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

    @srv.tool(name="vei.ping", description="Health check; returns ok and current logical time")
    def vei_ping() -> dict[str, Any]:
        return {"ok": True, "time_ms": R().bus.clock_ms}

    @srv.tool(name="vei.reset", description="Reset episode state; optionally supply a seed")
    def vei_reset(seed: int | None = None) -> dict[str, Any]:
        seed = seed if seed is not None else int(os.environ.get("VEI_SEED", "42042"))
        art = os.environ.get("VEI_ARTIFACTS_DIR")
        # Preserve scenario across resets
        scenario = holder.router.scenario if hasattr(holder.router, "scenario") else None
        holder.router = Router(seed=seed, artifacts_dir=art, scenario=scenario)
        return {"ok": True, "seed": seed}

    return srv
