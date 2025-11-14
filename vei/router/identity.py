from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from vei.identity.api import (
    IdentityApplication,
    IdentityGroup,
    IdentityUser,
    apps_from_seeds,
    groups_from_seeds,
    users_from_seeds,
)
from vei.world.scenario import (
    IdentityApplicationSeed,
    IdentityGroupSeed,
    IdentityUserSeed,
    Scenario,
)

from .errors import MCPError
from .tool_providers import PrefixToolProvider
from .tool_registry import ToolSpec


def _default_user_seeds() -> Dict[str, IdentityUserSeed]:
    return {
        "USR-9001": IdentityUserSeed(
            user_id="USR-9001",
            email="jane@example.com",
            login="jane",
            first_name="Jane",
            last_name="Castillo",
            title="Security Lead",
            department="Security",
            groups=["GRP-security"],
            applications=["APP-sso"],
        ),
        "USR-9002": IdentityUserSeed(
            user_id="USR-9002",
            email="mike@example.com",
            login="mike",
            first_name="Mike",
            last_name="Dorsey",
            title="IT Analyst",
            department="IT",
            status="SUSPENDED",
            groups=["GRP-it"],
            applications=["APP-sso"],
        ),
    }


def _default_group_seeds() -> Dict[str, IdentityGroupSeed]:
    return {
        "GRP-security": IdentityGroupSeed(
            group_id="GRP-security",
            name="Security Admins",
            description="Manage identity profiles and MFA",
            members=["USR-9001"],
        ),
        "GRP-it": IdentityGroupSeed(
            group_id="GRP-it",
            name="IT Support",
            members=["USR-9002"],
        ),
    }


def _default_app_seeds() -> Dict[str, IdentityApplicationSeed]:
    return {
        "APP-sso": IdentityApplicationSeed(
            app_id="APP-sso",
            label="Macro SSO",
            description="Corporate identity provider",
            assignments=["USR-9001", "USR-9002"],
        )
    }


class OktaSim:
    """Deterministic Okta-like identity emulator."""

    def __init__(self, scenario: Optional[Scenario] = None):
        user_seeds = (
            list((scenario.identity_users or _default_user_seeds()).values())
            if scenario
            else list(_default_user_seeds().values())
        )
        group_seeds = (
            list((scenario.identity_groups or _default_group_seeds()).values())
            if scenario
            else list(_default_group_seeds().values())
        )
        app_seeds = (
            list((scenario.identity_applications or _default_app_seeds()).values())
            if scenario
            else list(_default_app_seeds().values())
        )

        self.users: Dict[str, IdentityUser] = users_from_seeds(user_seeds)
        self.groups: Dict[str, IdentityGroup] = groups_from_seeds(group_seeds)
        self.apps: Dict[str, IdentityApplication] = apps_from_seeds(app_seeds)
        self._sync_relationships()
        self._reset_seq = 1

    def _sync_relationships(self) -> None:
        for group in self.groups.values():
            for member in list(group.members):
                if member not in self.users:
                    continue
                user = self.users[member]
                if group.group_id not in user.groups:
                    user.groups.append(group.group_id)
        for app in self.apps.values():
            for member in list(app.assignments):
                if member not in self.users:
                    continue
                user = self.users[member]
                if app.app_id not in user.applications:
                    user.applications.append(app.app_id)

    def list_users(
        self,
        status: Optional[str] = None,
        query: Optional[str] = None,
        include_groups: bool = False,
    ) -> Dict[str, Any]:
        normalized = status.upper() if status else None
        needle = (query or "").strip().lower()
        payload: List[Dict[str, Any]] = []
        for user in sorted(self.users.values(), key=lambda u: (u.status, u.email)):
            if normalized and user.status.upper() != normalized:
                continue
            if (
                needle
                and needle not in user.email.lower()
                and needle not in (user.display_name or "").lower()
            ):
                continue
            row = user.summary()
            if include_groups:
                row["groups"] = list(user.groups)
            payload.append(row)
        return {"users": payload, "count": len(payload)}

    def get_user(self, user_id: str) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        return user.detail()

    def activate_user(self, user_id: str) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        if user.status == "ACTIVE":
            return {"id": user_id, "status": "ACTIVE", "changed": False}
        updated = user.model_copy(update={"status": "ACTIVE"})
        self.users[user_id] = updated
        return {"id": user_id, "status": updated.status, "changed": True}

    def deactivate_user(
        self, user_id: str, reason: Optional[str] = None
    ) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        if user.status == "DEPROVISIONED":
            raise MCPError(
                "okta.invalid_state", f"User already deprovisioned: {user_id}"
            )
        updated = user.model_copy(update={"status": "DEPROVISIONED"})
        self.users[user_id] = updated
        return {"id": user_id, "status": updated.status, "reason": reason or "manual"}

    def reset_password(self, user_id: str) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        if user.status not in {"ACTIVE", "PROVISIONED", "SUSPENDED"}:
            raise MCPError(
                "okta.invalid_state",
                f"Cannot reset password for {user.status.lower()} user",
            )
        token = f"RST-{self._reset_seq:04d}-{user.user_id}"
        self._reset_seq += 1
        return {"user_id": user.user_id, "reset_token": token, "expires_ms": 3_600_000}

    def list_groups(
        self, query: Optional[str] = None, include_members: bool = False
    ) -> Dict[str, Any]:
        needle = (query or "").strip().lower()
        payload: List[Dict[str, Any]] = []
        for group in sorted(self.groups.values(), key=lambda g: g.name):
            if needle and needle not in group.name.lower():
                continue
            row = group.summary()
            if include_members:
                row["members"] = list(group.members)
            payload.append(row)
        return {"groups": payload, "count": len(payload)}

    def assign_group(self, user_id: str, group_id: str) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        group = self.groups.get(group_id)
        if not group:
            raise MCPError("okta.group_not_found", f"Unknown group: {group_id}")
        if user_id not in group.members:
            group.members.append(user_id)
        if group_id not in user.groups:
            user.groups.append(group_id)
        return {"group_id": group_id, "user_id": user_id, "members": len(group.members)}

    def list_applications(self, query: Optional[str] = None) -> Dict[str, Any]:
        needle = (query or "").strip().lower()
        payload: List[Dict[str, Any]] = []
        for app in sorted(self.apps.values(), key=lambda a: a.label):
            if needle and needle not in app.label.lower():
                continue
            payload.append(app.summary())
        return {"applications": payload, "count": len(payload)}

    def assign_application(self, user_id: str, app_id: str) -> Dict[str, Any]:
        user = self.users.get(user_id)
        if not user:
            raise MCPError("okta.user_not_found", f"Unknown user: {user_id}")
        app = self.apps.get(app_id)
        if not app:
            raise MCPError("okta.app_not_found", f"Unknown application: {app_id}")
        if user_id not in app.assignments:
            app.assignments.append(user_id)
        if app_id not in user.applications:
            user.applications.append(app_id)
        return {
            "user_id": user_id,
            "app_id": app_id,
            "assignments": len(app.assignments),
        }


class OktaToolProvider(PrefixToolProvider):
    """Tool provider exposing OktaSim operations via MCP tools."""

    def __init__(self, sim: OktaSim):
        super().__init__("okta", prefixes=("okta.",))
        self.sim = sim
        self._specs: List[ToolSpec] = [
            ToolSpec(
                name="okta.list_users",
                description="List Okta directory users optionally filtered by status or query.",
                permissions=("identity:read",),
                default_latency_ms=350,
                latency_jitter_ms=120,
            ),
            ToolSpec(
                name="okta.get_user",
                description="Fetch a single user profile by id.",
                permissions=("identity:read",),
                default_latency_ms=320,
                latency_jitter_ms=90,
            ),
            ToolSpec(
                name="okta.activate_user",
                description="Activate a user profile.",
                permissions=("identity:write",),
                side_effects=("identity_mutation",),
                default_latency_ms=420,
                latency_jitter_ms=140,
            ),
            ToolSpec(
                name="okta.deactivate_user",
                description="Deactivate or deprovision a user profile.",
                permissions=("identity:write",),
                side_effects=("identity_mutation",),
                default_latency_ms=450,
                latency_jitter_ms=150,
                fault_probability=0.01,
            ),
            ToolSpec(
                name="okta.reset_password",
                description="Generate a password reset token for a user.",
                permissions=("identity:write",),
                side_effects=("identity_mutation",),
                default_latency_ms=380,
                latency_jitter_ms=110,
            ),
            ToolSpec(
                name="okta.list_groups",
                description="List Okta groups optionally including member ids.",
                permissions=("identity:read",),
                default_latency_ms=330,
                latency_jitter_ms=100,
            ),
            ToolSpec(
                name="okta.assign_group",
                description="Add a user to an Okta group.",
                permissions=("identity:write",),
                side_effects=("identity_mutation",),
                default_latency_ms=410,
                latency_jitter_ms=140,
            ),
            ToolSpec(
                name="okta.list_applications",
                description="List SSO applications available in Okta.",
                permissions=("identity:read",),
                default_latency_ms=300,
                latency_jitter_ms=80,
            ),
            ToolSpec(
                name="okta.assign_application",
                description="Assign an application to a user.",
                permissions=("identity:write",),
                side_effects=("identity_mutation",),
                default_latency_ms=420,
                latency_jitter_ms=130,
            ),
        ]
        self._handlers: Dict[str, Callable[..., Any]] = {
            "okta.list_users": self.sim.list_users,
            "okta.get_user": self.sim.get_user,
            "okta.activate_user": self.sim.activate_user,
            "okta.deactivate_user": self.sim.deactivate_user,
            "okta.reset_password": self.sim.reset_password,
            "okta.list_groups": self.sim.list_groups,
            "okta.assign_group": self.sim.assign_group,
            "okta.list_applications": self.sim.list_applications,
            "okta.assign_application": self.sim.assign_application,
        }

    def specs(self) -> List[ToolSpec]:
        return list(self._specs)

    def call(self, tool: str, args: Dict[str, Any]) -> Any:
        handler = self._handlers.get(tool)
        if not handler:
            raise MCPError("unknown_tool", f"No such tool: {tool}")
        try:
            payload = args or {}
            return handler(**payload)
        except TypeError as exc:  # pragma: no cover - surfaced via MCPError
            raise MCPError("invalid_args", str(exc)) from exc
