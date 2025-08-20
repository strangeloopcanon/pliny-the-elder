from __future__ import annotations

from typing import Any, Dict, List, Optional

from vei.world.scenario import Scenario


class CrmSim:
    """Minimal deterministic CRM twin.

    Scope (v0):
    - Contacts: create/get/list
    - Companies: create/get/list
    - Associations: associate contact<->company
    - Deals: create/get/list/update_stage
    - Activities: log note/email (for SLA checks)

    Consent: if a contact has do_not_contact=True, activity logging with kind 'email_outreach'
    returns an error when error_rate triggers or policy is violated.
    """

    def __init__(self, bus, scenario: Optional[Scenario] = None):  # noqa: ANN001
        import os

        self.bus = bus
        self.contacts: Dict[str, Dict[str, Any]] = {}
        self.companies: Dict[str, Dict[str, Any]] = {}
        self.deals: Dict[str, Dict[str, Any]] = {}
        self.activities: List[Dict[str, Any]] = []
        self._c_seq = 1
        self._co_seq = 1
        self._d_seq = 1
        try:
            self.error_rate = float(os.environ.get("VEI_CRM_ERROR_RATE", "0"))
        except Exception:
            self.error_rate = 0.0

    # Contacts
    def create_contact(self, email: str, first_name: str | None = None, last_name: str | None = None, do_not_contact: bool = False) -> Dict[str, Any]:
        cid = f"C-{self._c_seq}"
        self._c_seq += 1
        self.contacts[cid] = {
            "id": cid,
            "email": email,
            "first_name": first_name or "",
            "last_name": last_name or "",
            "do_not_contact": bool(do_not_contact),
            "company_id": None,
            "created_ms": self.bus.clock_ms,
        }
        return {"id": cid}

    def get_contact(self, id: str) -> Dict[str, Any]:
        c = self.contacts.get(id)
        if not c:
            return {"error": {"code": "unknown_contact", "message": f"Unknown contact: {id}"}}
        return c

    def list_contacts(self) -> List[Dict[str, Any]]:
        return list(self.contacts.values())

    # Companies
    def create_company(self, name: str, domain: str | None = None) -> Dict[str, Any]:
        coid = f"CO-{self._co_seq}"
        self._co_seq += 1
        self.companies[coid] = {
            "id": coid,
            "name": name,
            "domain": domain or "",
            "created_ms": self.bus.clock_ms,
        }
        return {"id": coid}

    def get_company(self, id: str) -> Dict[str, Any]:
        co = self.companies.get(id)
        if not co:
            return {"error": {"code": "unknown_company", "message": f"Unknown company: {id}"}}
        return co

    def list_companies(self) -> List[Dict[str, Any]]:
        return list(self.companies.values())

    # Associations
    def associate_contact_company(self, contact_id: str, company_id: str) -> Dict[str, Any]:
        c = self.contacts.get(contact_id)
        if not c:
            return {"error": {"code": "unknown_contact", "message": f"Unknown contact: {contact_id}"}}
        if company_id not in self.companies:
            return {"error": {"code": "unknown_company", "message": f"Unknown company: {company_id}"}}
        c["company_id"] = company_id
        return {"ok": True}

    # Deals
    def create_deal(self, name: str, amount: float, stage: str = "New", contact_id: str | None = None, company_id: str | None = None) -> Dict[str, Any]:
        did = f"D-{self._d_seq}"
        self._d_seq += 1
        self.deals[did] = {
            "id": did,
            "name": name,
            "amount": float(amount),
            "stage": stage,
            "contact_id": contact_id,
            "company_id": company_id,
            "created_ms": self.bus.clock_ms,
            "updated_ms": self.bus.clock_ms,
        }
        return {"id": did}

    def get_deal(self, id: str) -> Dict[str, Any]:
        d = self.deals.get(id)
        if not d:
            return {"error": {"code": "unknown_deal", "message": f"Unknown deal: {id}"}}
        return d

    def list_deals(self) -> List[Dict[str, Any]]:
        return list(self.deals.values())

    def update_deal_stage(self, id: str, stage: str) -> Dict[str, Any]:
        d = self.deals.get(id)
        if not d:
            return {"error": {"code": "unknown_deal", "message": f"Unknown deal: {id}"}}
        d["stage"] = stage
        d["updated_ms"] = self.bus.clock_ms
        return {"ok": True, "stage": stage}

    # Activities
    def log_activity(self, kind: str, contact_id: str | None = None, deal_id: str | None = None, note: str | None = None) -> Dict[str, Any]:
        # Policy: if outreach to a DNC contact, sometimes error depending on error_rate
        if kind == "email_outreach" and contact_id:
            c = self.contacts.get(contact_id)
            if c and c.get("do_not_contact"):
                if self.error_rate > 0 and self.bus.rng.next_float() < self.error_rate:
                    return {"error": {"code": "consent_violation", "message": "Contact is marked do-not-contact."}}
        rec = {
            "time_ms": self.bus.clock_ms,
            "kind": kind,
            "contact_id": contact_id,
            "deal_id": deal_id,
            "note": note or "",
        }
        self.activities.append(rec)
        return {"ok": True}

