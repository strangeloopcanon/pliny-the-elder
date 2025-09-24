from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import server as fserver
from pydantic import BaseModel, Field

from .core import Router, MCPError
from .alias_packs import ERP_ALIAS_PACKS, CRM_ALIAS_PACKS


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

    @srv.tool(name="docs.list", description="List knowledge base documents")
    def docs_list() -> list[dict[str, Any]]:
        return R().call_and_step("docs.list", {})  # type: ignore[return-value]

    @srv.tool(name="docs.read", description="Read a document")
    def docs_read(doc_id: str) -> dict[str, Any]:
        try:
            return R().call_and_step("docs.read", {"doc_id": doc_id})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="docs.search", description="Search documents")
    def docs_search(query: str) -> list[dict[str, Any]]:
        return R().call_and_step("docs.search", {"query": query})  # type: ignore[return-value]

    @srv.tool(name="docs.create", description="Create a document")
    def docs_create(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
        return R().call_and_step("docs.create", {"title": title, "body": body, "tags": tags})

    @srv.tool(name="docs.update", description="Update a document")
    def docs_update(doc_id: str, title: str | None = None, body: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        try:
            return R().call_and_step(
                "docs.update",
                {"doc_id": doc_id, "title": title, "body": body, "tags": tags},
            )
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="calendar.list_events", description="List calendar events")
    def calendar_list_events() -> list[dict[str, Any]]:
        return R().call_and_step("calendar.list_events", {})  # type: ignore[return-value]

    @srv.tool(name="calendar.create_event", description="Create a calendar event")
    def calendar_create_event(
        title: str,
        start_ms: int,
        end_ms: int,
        attendees: list[str] | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return R().call_and_step(
            "calendar.create_event",
            {
                "title": title,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "attendees": attendees,
                "location": location,
                "description": description,
            },
        )

    @srv.tool(name="calendar.accept", description="Accept a calendar invite")
    def calendar_accept(event_id: str, attendee: str) -> dict[str, Any]:
        try:
            return R().call_and_step("calendar.accept", {"event_id": event_id, "attendee": attendee})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="calendar.decline", description="Decline a calendar invite")
    def calendar_decline(event_id: str, attendee: str) -> dict[str, Any]:
        try:
            return R().call_and_step("calendar.decline", {"event_id": event_id, "attendee": attendee})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="tickets.list", description="List tickets")
    def tickets_list() -> list[dict[str, Any]]:
        return R().call_and_step("tickets.list", {})  # type: ignore[return-value]

    @srv.tool(name="tickets.get", description="Get ticket detail")
    def tickets_get(ticket_id: str) -> dict[str, Any]:
        try:
            return R().call_and_step("tickets.get", {"ticket_id": ticket_id})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="tickets.create", description="Create a ticket")
    def tickets_create(title: str, description: str | None = None, assignee: str | None = None) -> dict[str, Any]:
        return R().call_and_step(
            "tickets.create",
            {"title": title, "description": description, "assignee": assignee},
        )

    @srv.tool(name="tickets.update", description="Update a ticket")
    def tickets_update(ticket_id: str, description: str | None = None, assignee: str | None = None) -> dict[str, Any]:
        try:
            return R().call_and_step(
                "tickets.update",
                {"ticket_id": ticket_id, "description": description, "assignee": assignee},
            )
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="tickets.transition", description="Transition ticket status")
    def tickets_transition(ticket_id: str, status: str) -> dict[str, Any]:
        try:
            return R().call_and_step("tickets.transition", {"ticket_id": ticket_id, "status": status})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="browser.read", description="Read current page")
    def browser_read() -> dict[str, Any]:
        return R().call_and_step("browser.read", {})

    @srv.tool(name="browser.back", description="Navigate back")
    def browser_back() -> dict[str, Any]:
        return R().call_and_step("browser.back", {})

    # --- ERP twin tools ---
    @srv.tool(name="erp.create_po", description="Create a purchase order (PO)")
    def erp_create_po(vendor: str, currency: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            return R().call_and_step("erp.create_po", {"vendor": vendor, "currency": currency, "lines": lines})
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="erp.get_po", description="Get a PO by id")
    def erp_get_po(id: str) -> dict[str, Any]:
        return R().call_and_step("erp.get_po", {"id": id})

    @srv.tool(name="erp.list_pos", description="List all POs")
    def erp_list_pos() -> list[dict[str, Any]]:
        return R().call_and_step("erp.list_pos", {})  # type: ignore[return-value]

    @srv.tool(name="erp.receive_goods", description="Receive goods against a PO")
    def erp_receive_goods(po_id: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        return R().call_and_step("erp.receive_goods", {"po_id": po_id, "lines": lines})

    @srv.tool(name="erp.submit_invoice", description="Submit an invoice for a PO")
    def erp_submit_invoice(vendor: str, po_id: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        return R().call_and_step("erp.submit_invoice", {"vendor": vendor, "po_id": po_id, "lines": lines})

    @srv.tool(name="erp.get_invoice", description="Get invoice by id")
    def erp_get_invoice(id: str) -> dict[str, Any]:
        return R().call_and_step("erp.get_invoice", {"id": id})

    @srv.tool(name="erp.list_invoices", description="List invoices")
    def erp_list_invoices() -> list[dict[str, Any]]:
        return R().call_and_step("erp.list_invoices", {})  # type: ignore[return-value]

    @srv.tool(name="erp.match_three_way", description="Three-way match PO vs receipt vs invoice")
    def erp_match_three_way(po_id: str, invoice_id: str, receipt_id: str | None = None) -> dict[str, Any]:
        return R().call_and_step("erp.match_three_way", {"po_id": po_id, "invoice_id": invoice_id, "receipt_id": receipt_id})

    @srv.tool(name="erp.post_payment", description="Post a payment against an invoice")
    def erp_post_payment(invoice_id: str, amount: float) -> dict[str, Any]:
        return R().call_and_step("erp.post_payment", {"invoice_id": invoice_id, "amount": amount})

    # --- CRM twin tools ---
    @srv.tool(name="crm.create_contact", description="Create a CRM contact")
    def crm_create_contact(email: str, first_name: str | None = None, last_name: str | None = None, do_not_contact: bool = False) -> dict[str, Any]:
        return R().call_and_step("crm.create_contact", {"email": email, "first_name": first_name, "last_name": last_name, "do_not_contact": do_not_contact})

    @srv.tool(name="crm.get_contact", description="Get contact by id")
    def crm_get_contact(id: str) -> dict[str, Any]:
        return R().call_and_step("crm.get_contact", {"id": id})

    @srv.tool(name="crm.list_contacts", description="List contacts")
    def crm_list_contacts() -> list[dict[str, Any]]:
        return R().call_and_step("crm.list_contacts", {})  # type: ignore[return-value]

    @srv.tool(name="crm.create_company", description="Create a company")
    def crm_create_company(name: str, domain: str | None = None) -> dict[str, Any]:
        return R().call_and_step("crm.create_company", {"name": name, "domain": domain})

    @srv.tool(name="crm.get_company", description="Get company by id")
    def crm_get_company(id: str) -> dict[str, Any]:
        return R().call_and_step("crm.get_company", {"id": id})

    @srv.tool(name="crm.list_companies", description="List companies")
    def crm_list_companies() -> list[dict[str, Any]]:
        return R().call_and_step("crm.list_companies", {})  # type: ignore[return-value]

    @srv.tool(name="crm.associate_contact_company", description="Associate contact and company")
    def crm_associate_contact_company(contact_id: str, company_id: str) -> dict[str, Any]:
        return R().call_and_step("crm.associate_contact_company", {"contact_id": contact_id, "company_id": company_id})

    @srv.tool(name="crm.create_deal", description="Create a deal")
    def crm_create_deal(name: str, amount: float, stage: str = "New", contact_id: str | None = None, company_id: str | None = None) -> dict[str, Any]:
        return R().call_and_step("crm.create_deal", {"name": name, "amount": amount, "stage": stage, "contact_id": contact_id, "company_id": company_id})

    @srv.tool(name="crm.get_deal", description="Get deal by id")
    def crm_get_deal(id: str) -> dict[str, Any]:
        return R().call_and_step("crm.get_deal", {"id": id})

    @srv.tool(name="crm.list_deals", description="List deals")
    def crm_list_deals() -> list[dict[str, Any]]:
        return R().call_and_step("crm.list_deals", {})  # type: ignore[return-value]

    @srv.tool(name="crm.update_deal_stage", description="Update deal stage")
    def crm_update_deal_stage(id: str, stage: str) -> dict[str, Any]:
        return R().call_and_step("crm.update_deal_stage", {"id": id, "stage": stage})

    @srv.tool(name="crm.log_activity", description="Log activity (note/email_outreach)")
    def crm_log_activity(kind: str, contact_id: str | None = None, deal_id: str | None = None, note: str | None = None) -> dict[str, Any]:
        return R().call_and_step("crm.log_activity", {"kind": kind, "contact_id": contact_id, "deal_id": deal_id, "note": note})

    # --- Configurable alias packs (ERP) ---
    packs_env = os.environ.get("VEI_ALIAS_PACKS", "xero").strip()
    packs = [p.strip() for p in packs_env.split(",") if p.strip()]

    def _register_alias(alias_name: str, base_tool: str) -> None:
        # Register a thin passthrough tool dynamically
        @srv.tool(name=alias_name, description=f"Alias → {base_tool}")
        def _alias_passthrough(**kwargs: Any) -> dict[str, Any]:  # type: ignore[no-redef]
            try:
                return R().call_and_step(base_tool, dict(kwargs))
            except MCPError as e:
                return {"error": {"code": e.code, "message": e.message}}

    for pack in packs:
        for alias, base in ERP_ALIAS_PACKS.get(pack, []):
            _register_alias(alias, base)

    # CRM alias packs
    crm_packs_env = os.environ.get("VEI_CRM_ALIAS_PACKS", "hubspot").strip()
    crm_packs = [p.strip() for p in crm_packs_env.split(",") if p.strip()]
    for pack in crm_packs:
        for alias, base in CRM_ALIAS_PACKS.get(pack, []):
            _register_alias(alias, base)

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

    @srv.tool(name="vei.call", description="Call any tool name with args via the VEI router")
    def vei_call(tool: str, args: dict[str, Any] = Field(default_factory=dict)) -> dict[str, Any]:
        try:
            return R().call_and_step(tool, args)
        except MCPError as e:
            return {"error": {"code": e.code, "message": e.message}}

    @srv.tool(name="vei.tick", description="Advance logical time by dt_ms and deliver due events")
    def vei_tick(dt_ms: int = 1000) -> dict[str, Any]:
        return R().tick(dt_ms)

    @srv.tool(name="vei.pending", description="Return pending event counts without advancing time")
    def vei_pending() -> dict[str, int]:
        return R().pending()

    @srv.tool(name="vei.state", description="Inspect state head, receipts, and recent tool calls")
    def vei_state(include_state: bool = False, tool_tail: int = 20, include_receipts: bool = True) -> dict[str, Any]:
        return R().state_snapshot(
            include_state=include_state,
            tool_tail=tool_tail,
            include_receipts=include_receipts,
        )

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
                {"tool": "vei.state", "args": {"tool_tail": "int?", "include_state": "bool?"}},
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
                {"tool": "erp.create_po", "args": {"vendor": "str", "currency": "str", "lines": "[{item_id,desc,qty,unit_price}]"}},
                {"tool": "erp.list_pos", "args": {}},
                {"tool": "erp.submit_invoice", "args": {"vendor": "str", "po_id": "str", "lines": "[{item_id,qty,unit_price}]"}},
                {"tool": "erp.match_three_way", "args": {"po_id": "str", "invoice_id": "str", "receipt_id": "str?"}},
                {"tool": "crm.create_contact", "args": {"email": "str", "first_name": "str?", "last_name": "str?", "do_not_contact": "bool?"}},
                {"tool": "crm.create_company", "args": {"name": "str", "domain": "str?"}},
                {"tool": "crm.associate_contact_company", "args": {"contact_id": "str", "company_id": "str"}},
                {"tool": "crm.create_deal", "args": {"name": "str", "amount": "number", "stage": "str?", "contact_id": "str?", "company_id": "str?"}},
                {"tool": "crm.update_deal_stage", "args": {"id": "str", "stage": "str"}},
                {"tool": "crm.log_activity", "args": {"kind": "str", "contact_id": "str?", "deal_id": "str?", "note": "str?"}},
                {"tool": "vei.call", "args": {"tool": "str", "args": "object"}},
            ],
            "examples": [
                {"tool": "vei.observe", "args": {}},
                {"tool": "browser.read", "args": {}},
                {"tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Summary: budget $3200, citations included."}},
                {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."}},
                {"tool": "vei.state", "args": {"tool_tail": 5}},
                {"tool": "vei.ping", "args": {}},
                {"tool": "vei.reset", "args": {"seed": 42042}},
                {"tool": "vei.act_and_observe", "args": {"tool": "browser.read", "args": {}}},
                {"tool": "vei.call", "args": {"tool": "erp.list_pos", "args": {}}},
                {"tool": packs[0] + ".list_purchase_orders" if packs else "xero.list_purchase_orders", "args": {}},
            ],
        }

    return srv
