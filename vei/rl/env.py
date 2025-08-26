from __future__ import annotations

import json
from typing import Any, Dict, Tuple

try:
    import gymnasium as gym
    from gymnasium import spaces
except Exception as _e:  # pragma: no cover - optional extra
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]

from vei.router.core import Router


class VEIEnv:  # Gymnasium-compatible but avoids hard dependency at import time
    """
    Minimal Gymnasium-style wrapper around the VEI Router.

    Observation: dict from router.observe().
    Action: {"tool": str, "args": dict} matching MCP tools.
    Reward shaping:
      - sparse: +1 when a vendor email is parsed (price+eta observed), else 0
      - dense: +0.25 per subgoal (citations, approval, email_sent, email_parsed)
    """

    metadata = {"render_modes": []}

    def __init__(self, seed: int = 42042, reward_mode: str = "sparse") -> None:
        self.seed_value = int(seed)
        self.reward_mode = reward_mode
        self.router = Router(seed=self.seed_value, artifacts_dir=None)
        # Lazy spaces if gymnasium is available
        if spaces is not None:
            self.observation_space = spaces.Dict({})  # free-form dict
            self.action_space = spaces.Dict({
                "tool": spaces.Text(min_length=1),
                "args": spaces.Dict({}, optional_keys=None),
            })
        else:  # pragma: no cover
            self.observation_space = None  # type: ignore[assignment]
            self.action_space = None  # type: ignore[assignment]

        # Simple internal flags for subgoals
        self._saw_browser_read = False
        self._sent_email = False
        self._saw_approval = False
        self._email_parsed = False

        # Book-keeping for cost shaping
        self.steps = 0
        self.elapsed_ms = 0

    # Gymnasium signature: reset(self, *, seed=None, options=None)
    def reset(self, *, seed: int | None = None, options: Dict[str, Any] | None = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if seed is not None:
            self.seed_value = int(seed)
        self.router = Router(seed=self.seed_value, artifacts_dir=None)
        self._saw_browser_read = False
        self._sent_email = False
        self._saw_approval = False
        self._email_parsed = False
        self.steps = 0
        self.elapsed_ms = 0
        obs = self.router.observe().model_dump()
        return obs, {}

    # Gymnasium signature: step(self, action) -> obs, reward, terminated, truncated, info
    def step(self, action: Dict[str, Any]) -> Tuple[Dict[str, Any], float, bool, bool, Dict[str, Any]]:
        tool = action.get("tool", "vei.observe")
        args = action.get("args", {})
        data = self.router.act_and_observe(tool, args)
        obs = data["observation"]

        # Update subgoal flags from trace and last call
        self._update_subgoals_from_last(tool)
        self._update_subgoals_from_trace()

        # Track cumulative cost stats
        self.steps += 1
        self.elapsed_ms = self.router.bus.clock_ms

        reward = self._compute_reward()
        terminated = self._email_parsed  # episode ends when main goal achieved
        # Also terminate if no pending events and we've already sent email + approval processed
        pend = self.router.pending()
        no_pending = (pend.get("mail", 0) == 0) and (pend.get("slack", 0) == 0)
        if no_pending and self._sent_email:
            terminated = terminated or True

        truncated = False
        info = {
            "subgoals": {
                "citations": int(self._saw_browser_read),
                "approval": int(self._saw_approval),
                "email_sent": int(self._sent_email),
                "email_parsed": int(self._email_parsed),
            },
            "costs": {"actions": self.steps, "time_ms": self.elapsed_ms},
        }
        return obs, float(reward), bool(terminated), bool(truncated), info

    def _compute_reward(self) -> float:
        if self.reward_mode == "dense":
            base = 0.25 * (
                int(self._saw_browser_read)
                + int(self._saw_approval)
                + int(self._sent_email)
                + int(self._email_parsed)
            )
        else:
            base = 1.0 if self._email_parsed else 0.0

        # Small penalty proportional to cumulative actions and time
        penalty = 0.01 * self.steps + 1e-5 * self.elapsed_ms
        return base - penalty

    def _update_subgoals_from_last(self, tool: str) -> None:
        if tool == "browser.read":
            self._saw_browser_read = True
        if tool == "mail.compose":
            self._sent_email = True

    def _update_subgoals_from_trace(self) -> None:
        # Inspect recent events in router.trace.entries for approval signals and vendor email
        price_ok = False
        eta_ok = False
        for rec in self.router.trace.entries[-50:]:  # scan recent tail
            if rec.get("type") == "event":
                tgt = rec.get("target")
                payload = rec.get("payload", {})
                text = str(payload.get("text", ""))
                if tgt == "slack":
                    if (":white_check_mark:" in text) or ("approved" in text.lower()):
                        self._saw_approval = True
                if tgt == "mail":
                    body = str(payload.get("body_text", ""))
                    if not body:
                        continue
                    # heuristics align with scorer
                    if _has_price(body):
                        price_ok = True
                    if _has_eta(body):
                        eta_ok = True
        self._email_parsed = self._email_parsed or (price_ok and eta_ok)


def _has_price(text: str) -> bool:
    import re
    pat = re.compile(r"\b(?:price|total)\s*(?::|-)\s*(?:USD|US\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", re.I)
    return bool(pat.search(text))


def _has_eta(text: str) -> bool:
    import re
    pat = re.compile(r"\beta\s*(?::|-)\s*([^\n]+)", re.I)
    return bool(pat.search(text))



