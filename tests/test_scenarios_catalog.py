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
