from __future__ import annotations

from typing import Any, Dict, Tuple

from ..arg_helpers import default_args_for


class MenuIndexWrapper:
    """Wrap VEIEnv to accept menu indices instead of explicit tool dicts."""

    def __init__(self, env: Any) -> None:
        self.env = env
        self._last_menu: list[Dict[str, Any]] = []

    def reset(self, *args: Any, **kwargs: Any) -> Tuple[dict, dict]:
        obs, info = self.env.reset(*args, **kwargs)
        self._last_menu = list(obs.get("action_menu", [])) if isinstance(obs, dict) else []
        return obs, info

    def step(self, action: Any) -> Tuple[dict, float, bool, bool, dict]:
        menu = self._last_menu
        tool_action = self._translate_action(action, menu)
        obs, reward, terminated, truncated, info = self.env.step(tool_action)
        self._last_menu = list(obs.get("action_menu", [])) if isinstance(obs, dict) else []
        return obs, reward, terminated, truncated, info

    def _translate_action(self, action: Any, menu: list[Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(action, tuple):
            idx, overrides = action
        else:
            idx, overrides = action, None
        if not menu:
            raise IndexError("no actions available")
        idx = int(idx)
        if idx < 0 or idx >= len(menu):
            raise IndexError(f"action index {idx} out of range")
        entry = menu[idx]
        tool = entry.get("tool")
        args = default_args_for(entry)
        if overrides:
            args.update(overrides)
        if not tool:
            raise ValueError("menu entry lacks tool name")
        return {"tool": tool, "args": args}

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - delegation
        return getattr(self.env, name)
