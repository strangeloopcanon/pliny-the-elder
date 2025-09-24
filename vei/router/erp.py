from __future__ import annotations

from typing import Any, Dict, List, Optional

from vei.world.scenario import Scenario


class ErpSim:
    """Minimal, deterministic ERP twin exposing MCP-style tools.

    Scope (v0):
    - POs: create/get/list
    - Goods receipts: receive against PO
    - Invoices: submit/get/list
    - Three-way match: PO vs receipt vs invoice
    - Payments: post payment against invoice

    Data is kept in-memory and keyed by simple string IDs for determinism.
    Amount math is integer cents to avoid FP drift.
    """

    def __init__(self, bus, scenario: Optional[Scenario] = None):  # noqa: ANN001 (bus type local)
        self.bus = bus
        self._po_seq = 1
        self._inv_seq = 1
        self._rcpt_seq = 1
        self.currency_default = "USD"
        # Deterministic error injection (default off). Set VEI_ERP_ERROR_RATE like '0.05' for 5%.
        try:
            import os
            self.error_rate = float(os.environ.get("VEI_ERP_ERROR_RATE", "0"))
        except Exception:
            self.error_rate = 0.0

        # Stores
        self.pos: Dict[str, Dict[str, Any]] = {}
        self.invoices: Dict[str, Dict[str, Any]] = {}
        self.receipts: Dict[str, Dict[str, Any]] = {}

    # Helpers
    def _money_to_cents(self, x: float | int | str) -> int:
        try:
            return int(round(float(x) * 100))
        except Exception:
            return 0

    def _cents_to_money(self, c: int) -> float:
        return round(c / 100.0, 2)

    # Tools
    def create_po(self, vendor: str, currency: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
        po_id = f"PO-{self._po_seq}"
        self._po_seq += 1
        total_cents = 0
        po_lines: List[Dict[str, Any]] = []
        for i, ln in enumerate(lines, start=1):
            qty = int(ln.get("qty", 0))
            unit_cents = self._money_to_cents(ln.get("unit_price", 0))
            line_total = qty * unit_cents
            total_cents += line_total
            po_lines.append(
                {
                    "line_no": i,
                    "item_id": str(ln.get("item_id", i)),
                    "desc": ln.get("desc", ""),
                    "qty": qty,
                    "unit_price": self._cents_to_money(unit_cents),
                    "amount": self._cents_to_money(line_total),
                }
            )
        po = {
            "id": po_id,
            "vendor": vendor,
            "currency": currency or self.currency_default,
            "status": "OPEN",
            "lines": po_lines,
            "amount": self._cents_to_money(total_cents),
            "created_ms": self.bus.clock_ms,
        }
        self.pos[po_id] = po
        return {"id": po_id, "amount": po["amount"], "currency": po["currency"]}

    def get_po(self, id: str) -> Dict[str, Any]:
        po = self.pos.get(id)
        if not po:
            return {"error": {"code": "unknown_po", "message": f"Unknown PO: {id}"}}
        return po

    def list_pos(self) -> List[Dict[str, Any]]:
        return list(self.pos.values())

    def receive_goods(self, po_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
        if po_id not in self.pos:
            return {"error": {"code": "unknown_po", "message": f"Unknown PO: {po_id}"}}
        rcpt_id = f"RCPT-{self._rcpt_seq}"
        self._rcpt_seq += 1
        rcpt_lines = [
            {
                "item_id": str(ln.get("item_id")),
                "qty": int(ln.get("qty", 0)),
            }
            for ln in lines
        ]
        rcpt = {
            "id": rcpt_id,
            "po_id": po_id,
            "lines": rcpt_lines,
            "time_ms": self.bus.clock_ms,
        }
        self.receipts[rcpt_id] = rcpt
        return {"id": rcpt_id}

    def submit_invoice(self, vendor: str, po_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
        if po_id not in self.pos:
            return {"error": {"code": "unknown_po", "message": f"Unknown PO: {po_id}"}}
        # Occasionally simulate validation error
        if self.error_rate > 0 and self.bus.rng.next_float() < self.error_rate:
            return {"error": {"code": "validation_error", "message": "Duplicate invoice number or invalid tax."}}
        inv_id = f"INV-{self._inv_seq}"
        self._inv_seq += 1
        total_cents = 0
        inv_lines: List[Dict[str, Any]] = []
        for i, ln in enumerate(lines, start=1):
            qty = int(ln.get("qty", 0))
            unit_cents = self._money_to_cents(ln.get("unit_price", 0))
            line_total = qty * unit_cents
            total_cents += line_total
            inv_lines.append(
                {
                    "line_no": i,
                    "item_id": str(ln.get("item_id", i)),
                    "qty": qty,
                    "unit_price": self._cents_to_money(unit_cents),
                    "amount": self._cents_to_money(line_total),
                }
            )
        inv = {
            "id": inv_id,
            "po_id": po_id,
            "vendor": vendor,
            "status": "OPEN",
            "lines": inv_lines,
            "amount": self._cents_to_money(total_cents),
            "paid_amount": 0.0,
            "time_ms": self.bus.clock_ms,
        }
        self.invoices[inv_id] = inv
        return {"id": inv_id, "amount": inv["amount"]}

    def get_invoice(self, id: str) -> Dict[str, Any]:
        inv = self.invoices.get(id)
        if not inv:
            return {"error": {"code": "unknown_invoice", "message": f"Unknown invoice: {id}"}}
        return inv

    def list_invoices(self) -> List[Dict[str, Any]]:
        return list(self.invoices.values())

    def match_three_way(self, po_id: str, invoice_id: str, receipt_id: Optional[str] = None) -> Dict[str, Any]:
        po = self.pos.get(po_id)
        inv = self.invoices.get(invoice_id)
        rcpt = self.receipts.get(receipt_id) if receipt_id else None
        if not po or not inv:
            return {"error": {"code": "unknown_ref", "message": "PO or Invoice not found"}}
        # Build item->qty maps
        po_qty = {str(l["item_id"]): int(l["qty"]) for l in po.get("lines", [])}
        inv_qty = {str(l["item_id"]): int(l["qty"]) for l in inv.get("lines", [])}
        rcpt_qty = {str(l["item_id"]): int(l["qty"]) for l in (rcpt.get("lines", []) if rcpt else [])}
        # Compare amounts (within 1 cent)
        po_amount_c = self._money_to_cents(po.get("amount", 0))
        inv_amount_c = self._money_to_cents(inv.get("amount", 0))
        amount_ok = abs(po_amount_c - inv_amount_c) <= 1
        # Quantities
        qty_mismatches: List[Dict[str, Any]] = []
        items = set(po_qty) | set(inv_qty)
        for it in items:
            pq = po_qty.get(it, 0)
            iq = inv_qty.get(it, 0)
            rq = rcpt_qty.get(it, 0)
            if (pq != iq) or (rcpt is not None and iq > rq):
                qty_mismatches.append({"item_id": it, "po": pq, "invoice": iq, "received": rq})
        status = "MATCH" if (amount_ok and not qty_mismatches) else "MISMATCH"
        return {
            "status": status,
            "amount_ok": amount_ok,
            "qty_mismatches": qty_mismatches,
            "po_id": po_id,
            "invoice_id": invoice_id,
            "receipt_id": receipt_id,
        }

    def post_payment(self, invoice_id: str, amount: float) -> Dict[str, Any]:
        inv = self.invoices.get(invoice_id)
        if not inv:
            return {"error": {"code": "unknown_invoice", "message": f"Unknown invoice: {invoice_id}"}}
        # Rarely simulate payment gateway rejection
        if self.error_rate > 0 and self.bus.rng.next_float() < (self.error_rate / 2):
            return {"error": {"code": "payment_rejected", "message": "Bank rejected payment."}}
        paid_c = self._money_to_cents(inv.get("paid_amount", 0.0)) + self._money_to_cents(amount)
        total_c = self._money_to_cents(inv.get("amount", 0.0))
        inv["paid_amount"] = self._cents_to_money(min(paid_c, total_c))
        if paid_c >= total_c:
            inv["status"] = "PAID"
        return {"status": inv["status"], "paid_amount": inv["paid_amount"]}
