from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List, Optional

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


def _rand_from_range(rng: random.Random, val: Any) -> Any:
    if isinstance(val, list) and len(val) == 2:
        lo, hi = val
        if isinstance(lo, int) and isinstance(hi, int):
            return rng.randint(lo, hi)
        try:
            return rng.uniform(float(lo), float(hi))
        except Exception:
            return val
    return val


def generate_scenario(template: Dict[str, Any], seed: Optional[int] = None) -> Scenario:
    """Generate a Scenario from a parameter template.

    The template may define:
      - budget_cap_usd, derail_prob, slack_initial_message
      - vendors: list of {name, price: [lo,hi], eta_days: [lo,hi]}
      - browser_nodes
      - derail_events: list of {dt_ms, target, payload}
    Prices/ETAs are randomized within ranges using the given seed.
    """

    rng = random.Random(seed)
    variants: List[str] = []
    for v in template.get("vendors", []):
        name = v.get("name", "Vendor")
        price = _rand_from_range(rng, v.get("price"))
        eta = _rand_from_range(rng, v.get("eta_days"))
        variants.append(f"{name} quote: ${int(price)}, ETA: {int(eta)} days.")

    return Scenario(
        budget_cap_usd=template.get("budget_cap_usd"),
        derail_prob=template.get("derail_prob"),
        slack_initial_message=template.get("slack_initial_message"),
        vendor_reply_variants=variants or None,
        browser_nodes=template.get("browser_nodes"),
        derail_events=template.get("derail_events"),
    )


def load_from_env(seed: Optional[int] = None) -> Scenario:
    """Load a Scenario based on environment variables.

    VEI_SCENARIO selects a named scenario from the catalog.
    VEI_SCENARIO_CONFIG provides a JSON string or path to a JSON file
    defining a parameter template for :func:`generate_scenario`.
    VEI_SCENARIO_RANDOM=1 randomly chooses a catalog scenario when none
    of the above are provided.
    """

    name = os.environ.get("VEI_SCENARIO")
    if name:
        try:
            return get_scenario(name)
        except KeyError:
            pass

    cfg = os.environ.get("VEI_SCENARIO_CONFIG")
    if cfg:
        try:
            if os.path.exists(cfg):
                with open(cfg, "r", encoding="utf-8") as f:
                    template = json.load(f)
            else:
                template = json.loads(cfg)
            return generate_scenario(template, seed=seed)
        except Exception:
            return Scenario()

    if os.environ.get("VEI_SCENARIO_RANDOM", "0") == "1":
        rng = random.Random(seed)
        key = rng.choice(list(_CATALOG.keys()))
        return _CATALOG[key]

    return Scenario()

