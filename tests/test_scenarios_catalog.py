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

