"""Lightweight registry capturing tool metadata for router planning.

The router still invokes tool callables directly today; this registry simply
collects metadata so we can wire permissions, latency simulation, and
side-effect tracking in later phases without touching each call site
individually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    side_effects: Sequence[str] = field(default_factory=tuple)
    permissions: Sequence[str] = field(default_factory=tuple)
    default_latency_ms: int = 0
    nominal_cost: float = 0.0
    returns: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "side_effects": list(self.side_effects),
            "permissions": list(self.permissions),
            "default_latency_ms": self.default_latency_ms,
            "nominal_cost": self.nominal_cost,
            "returns": self.returns,
        }


class ToolRegistry:
    """Registry of `ToolSpec` objects keyed by fully-qualified tool name."""

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def update(self, name: str, **kwargs: object) -> None:
        if name not in self._specs:
            raise KeyError(name)
        current = self._specs[name]
        data = current.to_dict()
        data.update(kwargs)
        self._specs[name] = ToolSpec(**data)

    def list(self) -> Iterable[ToolSpec]:
        return tuple(self._specs.values())

    def describe(self) -> List[Dict[str, object]]:
        return [spec.to_dict() for spec in self.list()]

