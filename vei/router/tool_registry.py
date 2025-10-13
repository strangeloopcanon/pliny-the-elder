"""Lightweight registry capturing tool metadata for router planning.

The router still invokes tool callables directly today; this registry simply
collects metadata so we can wire permissions, latency simulation, and
side-effect tracking in later phases without touching each call site
individually.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    side_effects: Sequence[str] = field(default_factory=tuple)
    permissions: Sequence[str] = field(default_factory=tuple)
    default_latency_ms: int = 0
    latency_jitter_ms: int = 0
    nominal_cost: float = 0.0
    returns: Optional[str] = None
    fault_probability: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "side_effects": list(self.side_effects),
            "permissions": list(self.permissions),
            "default_latency_ms": self.default_latency_ms,
            "latency_jitter_ms": self.latency_jitter_ms,
            "nominal_cost": self.nominal_cost,
            "returns": self.returns,
            "fault_probability": self.fault_probability,
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

    def search(self, query: str, *, top_k: int = 10) -> List[Tuple[ToolSpec, float]]:
        """Return tool specs ranked by heuristic relevance to the query."""
        specs = list(self._specs.values())
        if not specs:
            return []

        limit = top_k if top_k and top_k > 0 else len(specs)
        normalized = (query or "").strip().lower()
        if not normalized:
            ranked = sorted(specs, key=lambda spec: spec.name)
            return [(spec, 0.0) for spec in ranked[:limit]]

        terms = [t for t in re.split(r"[\W_]+", normalized) if t]
        results: List[Tuple[ToolSpec, float]] = []
        for spec in specs:
            score = self._score_spec(spec, normalized, terms)
            results.append((spec, score))

        results.sort(key=lambda item: (-item[1], item[0].name))
        top_results = results[:limit]
        if top_results and top_results[0][1] <= 0.0:
            fallback = sorted(specs, key=lambda spec: spec.name)[:limit]
            return [(spec, 0.0) for spec in fallback]
        return top_results

    @staticmethod
    def _score_spec(spec: ToolSpec, normalized: str, terms: List[str]) -> float:
        name = spec.name.lower()
        description = (spec.description or "").lower()
        score = 0.0

        if normalized and normalized in name:
            score += 6.0
        if normalized and normalized in description:
            score += 2.5

        name_tokens = [tok for tok in re.split(r"[.\-:/_\s]+", name) if tok]
        desc_tokens = [tok for tok in re.split(r"[\W_]+", description) if tok]

        for term in terms:
            if term in name_tokens:
                score += 3.0
            else:
                starts_with_match = any(tok.startswith(term) for tok in name_tokens)
                if starts_with_match:
                    score += 1.5
            if term in desc_tokens:
                score += 1.0

        # Slight preference for deterministic VEI orchestrator tools when ties occur.
        if spec.name.startswith("vei."):
            score += 0.25
        return score
