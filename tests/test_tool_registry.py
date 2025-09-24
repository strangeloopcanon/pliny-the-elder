from __future__ import annotations

import pytest

from vei.router.tool_registry import ToolRegistry, ToolSpec


def test_register_and_get_spec() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="mail.compose",
        description="Compose an email",
        side_effects=("mail_outbound",),
        permissions=("mail:write",),
        default_latency_ms=1200,
        nominal_cost=0.02,
        returns="message_id",
    )
    registry.register(spec)

    fetched = registry.get("mail.compose")
    assert fetched is not None
    assert fetched.to_dict()["permissions"] == ["mail:write"]


def test_register_duplicate_raises() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="vei.observe", description="Observe state"))
    with pytest.raises(ValueError):
        registry.register(ToolSpec(name="vei.observe", description="duplicate"))


def test_update_overwrites_selected_fields() -> None:
    registry = ToolRegistry()
    registry.register(ToolSpec(name="slack.send_message", description="Send Slack"))
    registry.update("slack.send_message", default_latency_ms=500, nominal_cost=0.01)

    spec = registry.get("slack.send_message")
    assert spec is not None
    assert spec.default_latency_ms == 500
    assert spec.nominal_cost == 0.01

