from __future__ import annotations

from typing import Any, Dict


def default_args_for(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return default args for a menu entry, preferring explicit args over schema."""

    args = entry.get("args")
    if isinstance(args, dict):
        return dict(args)
    schema = entry.get("args_schema")
    if isinstance(schema, dict):
        resolved: Dict[str, Any] = {}
        for key, raw_hint in schema.items():
            hint = str(raw_hint)
            optional = hint.endswith("?")
            core = hint[:-1] if optional else hint
            if core.startswith("["):
                resolved[key] = []
            elif core in {"int", "number", "float"}:
                resolved[key] = 0
            else:
                resolved[key] = ""
        return resolved
    return {}
