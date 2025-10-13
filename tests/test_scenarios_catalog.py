from __future__ import annotations

from vei.router.core import Router
from vei.world.scenarios import get_scenario


def test_extended_store_navigation_flow():
    scen = get_scenario("extended_store")
    r = Router(seed=42, artifacts_dir=None, scenario=scen)

    # On home, there should be an affordance to open category
    hits = r.call_and_step("browser.find", {"query": "button", "top_k": 5})
    assert hits["hits"], "expected at least one affordance on home"
    node_id = hits["hits"][0]["node_id"]
    nav = r.call_and_step("browser.click", {"node_id": node_id})
    assert "url" in nav and "/cat/laptops" in nav["url"]

    # In category, open first product
    hits = r.call_and_step("browser.find", {"query": "button", "top_k": 5})
    node_id = hits["hits"][0]["node_id"]
    nav = r.call_and_step("browser.click", {"node_id": node_id})
    assert "/pdp/" in nav["url"]


def test_multi_channel_scenario_has_docs_and_tickets():
    scen = get_scenario("multi_channel")
    assert scen.documents and "policy" in scen.documents
    assert scen.tickets and "TCK-42" in scen.tickets

    r = Router(seed=99, artifacts_dir=None, scenario=scen)
    docs_list = r.call_and_step("docs.list", {})
    assert docs_list and docs_list[0]["title"]

    tickets = r.call_and_step("tickets.list", {})
    assert tickets and tickets[0]["ticket_id"] == "TCK-42"


def test_multi_channel_compliance_has_audit_assets():
    scen = get_scenario("multi_channel_compliance")
    assert scen.documents
    doc_ids = {doc.doc_id for doc in scen.documents.values()}
    assert {"POLICY-1", "PROC-7", "RISK-9"}.issubset(doc_ids)
    assert scen.tickets
    ticket_ids = {ticket.ticket_id for ticket in scen.tickets.values()}
    assert {"TCK-42", "TCK-88"}.issubset(ticket_ids)
    assert scen.participants and any(p.participant_id == "auditor-li" for p in scen.participants)
    assert scen.derail_events and len(scen.derail_events) >= 2

    r = Router(seed=101, artifacts_dir=None, scenario=scen)
    docs = r.call_and_step("docs.list", {})
    titles = {d["title"] for d in docs}
    assert "Procurement Checklist" in titles
    tickets = r.call_and_step("tickets.list", {})
    listed_ids = {t["ticket_id"] for t in tickets}
    assert {"TCK-42", "TCK-88"}.issubset(listed_ids)


def test_f2_knowledge_qa_scenario_loads_correctly():
    """Verify the F2 scenario loads with correct documents and events."""
    scen = get_scenario("f2_knowledge_qa")

    # Check that the necessary documents are defined
    assert scen.documents, "Scenario should have documents"
    assert "DOC-POLICY-REMOTE" in scen.documents
    assert "DOC-FAQ-STIPEND" in scen.documents
    assert "DOC-GUIDE-OLD" in scen.documents

    # Check that the outdated document is marked as such
    assert "OUTDATED" in scen.documents["DOC-GUIDE-OLD"].title

    # Check for the initial event
    assert scen.derail_events, "Scenario should have a derail event"
    assert scen.derail_events[0]["payload"]["user"] == "new-hire-jane"

    # Check that the router can be initialized and can list the docs
    r = Router(seed=42, artifacts_dir=None, scenario=scen)
    docs_list = r.call_and_step("docs.list", {})
    assert len(docs_list) == 3
    doc_titles = [doc["title"] for doc in docs_list]
    assert "Remote Work Policy (2025)" in doc_titles
    assert "Work From Home Guide (2022) - OUTDATED" in doc_titles


def test_f5_vendor_comparison_scenario_loads_correctly():
    """Verify the F5 scenario loads with correct browser nodes."""
    scen = get_scenario("f5_vendor_comparison")

    # Check that the browser nodes are defined
    assert scen.browser_nodes, "Scenario should have browser_nodes"
    assert "home" in scen.browser_nodes
    assert "macrocompute_pdp" in scen.browser_nodes
    assert "dell_pdp" in scen.browser_nodes
    assert "hp_pdp" in scen.browser_nodes

    # Check that the router can be initialized and can see the vendor links
    r = Router(seed=42, artifacts_dir=None, scenario=scen)
    obs = r.call_and_step("vei.observe", {})
    affordances = obs.get("action_menu", [])
    assert len(affordances) >= 3
    vendor_links = [a.get("name") for a in affordances if a.get("tool") == "browser.click"]
    assert "MacroCompute Store" in vendor_links
    assert "Dell Business" in vendor_links
