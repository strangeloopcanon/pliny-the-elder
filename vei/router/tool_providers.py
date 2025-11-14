from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Sequence, Tuple

from .tool_registry import ToolSpec


class ToolProvider(ABC):
    """Abstract base for pluggable MCP tool providers.

    Providers expose metadata (``ToolSpec`` entries) along with the logic needed
    to dispatch tool invocations. The router keeps a list of registered
    providers, making it possible to add new tool surfaces without editing the
    main dispatch table every time.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def specs(self) -> Sequence[ToolSpec]:
        """Return the tool specs contributed by this provider."""

    @abstractmethod
    def handles(self, tool: str) -> bool:
        """Return True if this provider can execute the given tool."""

    @abstractmethod
    def call(self, tool: str, args: Dict[str, Any]) -> Any:
        """Execute the tool call and return its result."""


class PrefixToolProvider(ToolProvider):
    """Utility base class for providers that handle set prefixes."""

    def __init__(self, name: str, prefixes: Iterable[str]) -> None:
        super().__init__(name)
        pref = tuple(prefixes)
        if not pref:
            raise ValueError("prefix list cannot be empty for PrefixToolProvider")
        self._prefixes: Tuple[str, ...] = pref

    def handles(self, tool: str) -> bool:  # pragma: no cover - trivial
        return any(tool.startswith(prefix) for prefix in self._prefixes)
