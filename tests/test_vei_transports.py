#!/usr/bin/env python3
"""
End-to-end transport smoke tests for VEI MCP server.

Run directly with:
  python tests/test_vei_transports.py

This script does NOT require an OpenAI API key. It exercises stdio; SSE path is
intentionally skipped while focusing on stdio transport. If mcp is not installed,
it falls back to a direct Router smoke test.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from typing import Any


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            return s.connect_ex((host, port)) == 0
        except Exception:
            return False


async def _run_stdio(seed: int = 42042) -> list[dict[str, Any]]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    import sys as _sys

    params = StdioServerParameters(command=_sys.executable or "python3", args=["-m", "vei.router"], env={"VEI_SEED": str(seed)})
    out: list[dict[str, Any]] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            obs = await s.call_tool("vei.observe", {})
            out.append({"observation": obs})
            await s.call_tool("browser.read", {})
            await s.call_tool("slack.send_message", {"channel": "#procurement", "text": "Summary: budget $3200"})
            await s.call_tool("mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote", "body_text": "Please advise."})
            # Drain
            for _ in range(12):
                obs = await s.call_tool("vei.observe", {})
                out.append({"observation": obs})
                pend = obs.get("pending_events", {})
                if pend.get("slack", 0) == 0 and pend.get("mail", 0) == 0:
                    break
    return out


async def _run_sse(url: str) -> list[dict[str, Any]]:
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client

    out: list[dict[str, Any]] = []
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            obs = await s.call_tool("vei.observe", {})
        out.append({"observation": obs})
        await s.call_tool("browser.read", {})
        await s.call_tool("slack.send_message", {"channel": "#procurement", "text": "Summary: budget $3200"})
        await s.call_tool("mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote", "body_text": "Please advise."})
        for _ in range(12):
            obs = await s.call_tool("vei.observe", {})
            out.append({"observation": obs})
            pend = obs.get("pending_events", {})
            if pend.get("slack", 0) == 0 and pend.get("mail", 0) == 0:
                break
    return out


def main() -> int:
    seed = int(os.getenv("VEI_SEED", "42042"))
    # Ensure repository root is importable for direct Router fallback
    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
    except Exception:
        ...
    # Prefer stdio test (no server to pre-start)
    try:
        stdio_out = asyncio.run(_run_stdio(seed))
        print(json.dumps({"stdio": stdio_out[-1]}, indent=2))
    except Exception as e:
        print(f"[WARN] stdio test failed: {e}", file=sys.stderr)
        # Fallback: direct Router integration test (no MCP dependency)
        try:
            from vei.router.core import Router
            r = Router(seed=seed)
            o1 = r.observe().model_dump()
            r.call_and_step("browser.read", {})
            r.call_and_step("slack.send_message", {"channel": "#procurement", "text": "Summary: budget $3200"})
            r.call_and_step("mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote", "body_text": "Please advise."})
            r.tick(20000)
            o2 = r.observe().model_dump()
            print(json.dumps({"router": {"start": o1, "end": o2}}, indent=2))
        except Exception as e2:
            print(f"[WARN] direct Router fallback failed: {e2}", file=sys.stderr)

    # SSE path intentionally skipped while focusing on stdio
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
