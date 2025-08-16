#!/usr/bin/env python3
"""
Standalone LLM stdio smoke runner.

Mirrors tests/test_llm_stdio_smoke.py but runnable directly:
 - Loads .env
 - Spawns stdio MCP server (python -m vei.router)
 - Calls OpenAI (model from VEI_MODEL or default gpt-5) to choose a tool
 - Executes chosen tool and verifies trace artifact

Usage:
  python examples/llm_smoke_run.py

Optional env:
  OPENAI_API_KEY=... [required]
  OPENAI_BASE_URL=... [optional]
  VEI_MODEL=gpt-5
  VEI_ARTIFACTS_DIR=_vei_out/llm_smoke
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(override=False)
    except Exception:
        ...


async def main() -> int:
    _load_env()

    # Artifacts directory
    art = Path(os.environ.get("VEI_ARTIFACTS_DIR", "_vei_out/llm_smoke")).resolve()
    art.mkdir(parents=True, exist_ok=True)
    os.environ["VEI_ARTIFACTS_DIR"] = str(art)

    # Spawn stdio MCP server
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.session import ClientSession
    import sys as _sys

    params = StdioServerParameters(
        command=_sys.executable or "python3",
        args=["-m", "vei.router"],
        env={
            **os.environ,
            "VEI_DISABLE_AUTOSTART": "1",
            "PYTHONUNBUFFERED": "1",
        },
    )

    from openai import AsyncOpenAI

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # One observation to seed context
            obs = await session.call_tool("vei.observe", {})
            assert obs is not None

            # Plan via OpenAI
            client = AsyncOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("OPENAI_BASE_URL"),
            )
            model = os.environ.get("VEI_MODEL", "gpt-5")
            system = (
                "You are a planner that MUST return a JSON object with keys 'tool' and 'args'. "
                "Choose 'browser.read' with {} as args. Reply with JSON only."
            )
            messages = [{"role": "system", "content": system}]

            chat = await client.chat.completions.create(model=model, messages=messages)
            content = chat.choices[0].message.content or "{}"
            try:
                plan = json.loads(content)
            except Exception:
                plan = {"tool": "browser.read", "args": {}}
            tool = plan.get("tool", "browser.read")
            args = plan.get("args", {})

            res = await session.call_tool(tool, args)
            # Basic validation
            sc = getattr(res, "structuredContent", None)
            if sc is not None:
                assert "url" in sc and "title" in sc
            else:
                content_list = getattr(res, "content", [])
                assert content_list, "expected content from tool result"

    trace = art / "trace.jsonl"
    print(f"Trace written to: {trace}")
    if trace.exists():
        try:
            with trace.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            print("Last 20 lines:")
            for line in lines[-20:]:
                print(line.rstrip())
        except Exception as e:
            print(f"Could not read trace tail: {e}")
        return 0
    else:
        print("Trace file not found; check server logs and env.")
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

