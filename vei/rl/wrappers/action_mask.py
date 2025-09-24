from __future__ import annotations

from typing import Any, Tuple


class ActionMaskWrapper:
    """Attach an action mask derived from the observation's action_menu."""

    def __init__(self, env: Any) -> None:
        self.env = env

    def reset(self, *args: Any, **kwargs: Any) -> Tuple[dict, dict]:
        obs, info = self.env.reset(*args, **kwargs)
        mask = self._mask_from_obs(obs)
        info = dict(info or {})
        info["action_mask"] = mask
        self._last_mask = mask
        return obs, info

    def step(self, action: Any) -> Tuple[dict, float, bool, bool, dict]:
        obs, reward, terminated, truncated, info = self.env.step(action)
        mask = self._mask_from_obs(obs)
        info = dict(info or {})
        info["action_mask"] = mask
        self._last_mask = mask
        return obs, reward, terminated, truncated, info

    def _mask_from_obs(self, obs: dict) -> list[int]:
        menu = obs.get("action_menu") if isinstance(obs, dict) else None
        if not menu:
            return []
        return [1] * len(menu)

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - delegation
        return getattr(self.env, name)
