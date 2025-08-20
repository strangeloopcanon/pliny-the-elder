from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import server as fserver

from .core import Router, MCPError


def create_erp_mcp_server(router: Router, host: str | None = None, port: int | None = None, mount_path: str = "/") -> fserver.FastMCP:
    if host is None:
        host = os.environ.get("VEI_HOST", "127.0.0.1")
    if port is None:
        try:
            port = int(os.environ.get("VEI_ERP_PORT", "3010"))
        except ValueError:
            port = 3010

    log_level = os.environ.get("FASTMCP_LOG_LEVEL", "INFO").upper()
    debug_flag = os.environ.get("FASTMCP_DEBUG", "0") in {"1", "true", "TRUE", "yes", "on"}

    ts = None
    if os.environ.get("FASTMCP_DISABLE_SECURITY") in {"1", "true", "TRUE", "yes", "on"}:
        try:
            from mcp.server.fastmcp.server import TransportSecuritySettings  # type: ignore
            ts = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        except Exception:
            ts = None

    srv = fserver.FastMCP(
        name="VEI ERP Twin",
        instructions="Synthetic ERP MCP server (PO/Receipt/Invoice/Match/Payment)",
        host=host,
        port=port,
        mount_path=mount_path,
        log_level=log_level,
        debug=debug_flag,
        transport_security=ts,
    )

    def R() -> Router:
        return router

    # ERP-only tools
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

    return srv

