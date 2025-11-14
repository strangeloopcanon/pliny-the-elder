from __future__ import annotations

import pytest

from vei.router.core import MCPError, Router
from vei.world.scenarios import scenario_multi_channel


@pytest.fixture()
def router():
    return Router(seed=1234, artifacts_dir=None, scenario=scenario_multi_channel())


def test_okta_tools_registered(router: Router):
    search = router.search_tools("okta")
    names = {entry["name"] for entry in search["results"]}
    assert "okta.list_users" in names
    assert "okta.assign_group" in names


def test_okta_group_assignment(router: Router):
    router.call_and_step(
        "okta.assign_group", {"user_id": "USR-2001", "group_id": "GRP-procurement"}
    )
    user = router.call_and_step("okta.get_user", {"user_id": "USR-2001"})
    assert "GRP-procurement" in user["groups"]


def test_okta_reset_password_rejects_deprovisioned(router: Router):
    with pytest.raises(MCPError) as exc:
        router.call_and_step("okta.reset_password", {"user_id": "USR-3001"})
    assert exc.value.code == "okta.invalid_state"
