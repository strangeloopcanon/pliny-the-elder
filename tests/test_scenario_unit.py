from __future__ import annotations

from vei.router.core import Router
from vei.world.scenario import Scenario


def test_scenario_budget_cap_overridden():
    # Tighten budget cap to force an over-cap response
    scen = Scenario(budget_cap_usd=1000, derail_prob=0.0)
    r = Router(seed=123, artifacts_dir=None, scenario=scen)
    ch = "#procurement"

    # Ask for approval with budget 2000 (over cap)
    r.call_and_step("slack.send_message", {"channel": ch, "text": "Request approval, budget $2000"})

    # Advance time to allow scheduled response (10s)
    for _ in range(15):
        r.observe("slack")

    msgs = r.slack.channels[ch]["messages"]
    assert any("over cap" in m.get("text", "").lower() for m in msgs)

