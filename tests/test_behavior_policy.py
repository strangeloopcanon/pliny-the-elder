from __future__ import annotations

from vei.behavior import ScriptedProcurementPolicy
from vei.router.core import Router


def test_scripted_procurement_policy_executes_sequence() -> None:
    router = Router(seed=123, artifacts_dir=None)

    runner = ScriptedProcurementPolicy(router)
    transcript = runner.run()

    tools_used = [entry.get("tool") for entry in transcript if "tool" in entry]
    assert "slack.send_message" in tools_used
    assert "mail.compose" in tools_used
    # Ensure at least one observation recorded
    assert any("observation" in entry for entry in transcript)
