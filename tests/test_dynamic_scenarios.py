from __future__ import annotations

import json

from vei.router.core import Router
from vei.world.scenarios import generate_scenario
from vei.config import Config


def test_generate_scenario_and_derail(monkeypatch):
    template = {
        "budget_cap_usd": 4000,
        "derail_prob": 0.0,
        "vendors": [
            {"name": "VendorA", "price": [1000, 1100], "eta_days": [5, 5]},
            {"name": "VendorB", "price": [1200, 1300], "eta_days": [7, 7]},
        ],
        "derail_events": [
            {
                "dt_ms": 2000,
                "target": "slack",
                "payload": {"channel": "#procurement", "text": "off topic", "thread_ts": None},
            }
        ],
    }
    scen = generate_scenario(template, seed=123)
    r = Router(seed=123, artifacts_dir=None, scenario=scen)

    # Trigger vendor reply
    r.call_and_step("mail.compose", {"to": "sales@example", "subj": "quote", "body_text": "hi"})
    for _ in range(20):
        r.observe("mail")
    inbox = r.mail.list()
    assert any("VendorA" in m["body_text"] or "VendorB" in m["body_text"] for m in inbox)

    # Ensure derail event delivered
    r.observe("slack")
    r.observe("slack")
    messages = [m["text"] for m in r.slack.channels["#procurement"]["messages"]]
    assert any("off topic" in m for m in messages)


def test_load_scenario_from_env(tmp_path, monkeypatch):
    template = {
        "budget_cap_usd": 3000,
        "vendors": [{"name": "EnvVendor", "price": [1500, 1600], "eta_days": [3, 4]}],
    }
    path = tmp_path / "scen.json"
    path.write_text(json.dumps(template))
    monkeypatch.setenv("VEI_SCENARIO_CONFIG", str(path))
    r = Router(seed=1, artifacts_dir=None)
    assert r.scenario.vendor_reply_variants is not None
    assert any("EnvVendor" in v for v in r.scenario.vendor_reply_variants)
    monkeypatch.delenv("VEI_SCENARIO_CONFIG", raising=False)


def test_config_from_env(tmp_path, monkeypatch):
    template = {
        "budget_cap_usd": 2500,
        "vendors": [{"name": "CfgVendor", "price": [900, 1000], "eta_days": [4, 4]}],
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(template))
    monkeypatch.setenv("VEI_SCENARIO_CONFIG", str(path))
    cfg = Config.from_env()
    assert cfg.scenario is not None
    assert any(
        "CfgVendor" in v for v in (cfg.scenario.vendor_reply_variants or [])
    )
    monkeypatch.delenv("VEI_SCENARIO_CONFIG", raising=False)
