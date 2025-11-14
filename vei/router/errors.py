from __future__ import annotations


class MCPError(Exception):
    """Consistent error type surfaced to MCP clients."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)
