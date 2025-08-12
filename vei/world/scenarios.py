from __future__ import annotations

from typing import Dict

from .scenario import Scenario


def scenario_macrocompute_default() -> Scenario:
    return Scenario(
        budget_cap_usd=3500,
        derail_prob=0.1,
        slack_initial_message="Reminder: citations required for any request over $2k.",
        vendor_reply_variants=[
            "Thanks — Price: $3199, ETA: 5-7 business days.",
            "> On Mon, we received your request\nPRICE: USD 3,199\nEta: within 5-7 business days\n--\nBest, MacroCompute",
            "quote attached (inline): total: $3,199.00, ETA: 5 business days. Regards, Sales",
            "PRICE - $3199; eta: approx. 1 week\n\n\nJohn Doe\nSales Representative\nMacroCompute",
        ],
        browser_nodes=None,
    )


def scenario_extended_store() -> Scenario:
    nodes = {
        "home": {
            "url": "https://vweb.local/home",
            "title": "MacroCompute — Home",
            "excerpt": "Welcome. Browse categories to find laptops and accessories.",
            "affordances": [
                {"tool": "browser.click", "args": {"node_id": "CLICK:open_category#0"}},
            ],
            "next": {"CLICK:open_category#0": "category"},
        },
        "category": {
            "url": "https://vweb.local/cat/laptops",
            "title": "Laptops — Category",
            "excerpt": "Showing 2 results",
            "affordances": [
                {"tool": "browser.click", "args": {"node_id": "CLICK:open_pdp1#0"}},
                {"tool": "browser.click", "args": {"node_id": "CLICK:open_pdp2#0"}},
                {"tool": "browser.back", "args": {}},
            ],
            "next": {"CLICK:open_pdp1#0": "pdp1", "CLICK:open_pdp2#0": "pdp2", "BACK": "home"},
        },
        "pdp1": {
            "url": "https://vweb.local/pdp/macrobook-pro-16",
            "title": "MacroBook Pro 16 — Product",
            "excerpt": "Powerful 16-inch laptop. Price $3199. See specifications.",
            "affordances": [
                {"tool": "browser.click", "args": {"node_id": "CLICK:open_specs1#0"}},
                {"tool": "browser.back", "args": {}},
            ],
            "next": {"CLICK:open_specs1#0": "specs1", "BACK": "category"},
        },
        "specs1": {
            "url": "https://vweb.local/pdp/macrobook-pro-16/specs",
            "title": "MacroBook Pro 16 — Specifications",
            "excerpt": "16-core CPU, 32GB RAM, 1TB SSD",
            "affordances": [{"tool": "browser.back", "args": {}}],
            "next": {"BACK": "pdp1"},
        },
        "pdp2": {
            "url": "https://vweb.local/pdp/macrobook-air-13",
            "title": "MacroBook Air 13 — Product",
            "excerpt": "Lightweight 13-inch laptop. Price $1299.",
            "affordances": [
                {"tool": "browser.back", "args": {}},
            ],
            "next": {"BACK": "category"},
        },
    }
    return Scenario(
        budget_cap_usd=3500,
        derail_prob=0.05,
        slack_initial_message="Reminder: include budget and citations.",
        vendor_reply_variants=None,
        browser_nodes=nodes,
    )


_CATALOG: Dict[str, Scenario] = {
    "macrocompute_default": scenario_macrocompute_default(),
    "extended_store": scenario_extended_store(),
}


def get_scenario(name: str) -> Scenario:
    key = name.strip().lower()
    if key in _CATALOG:
        return _CATALOG[key]
    raise KeyError(f"Unknown scenario: {name}")


def list_scenarios() -> Dict[str, Scenario]:
    return dict(_CATALOG)

