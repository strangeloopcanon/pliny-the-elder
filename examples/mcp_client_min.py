from __future__ import annotations

import asyncio
import json
import os

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


async def main() -> None:
    url = os.getenv("VEI_SSE_URL", "http://127.0.0.1:3001/sse")
    async with sse_client(url) as (read, write):
        s = ClientSession(read, write)
        await s.initialize()
        obs = await s.call_tool("vei.observe", {})
        print(json.dumps(obs, indent=2))
        res = await s.call_tool("browser.read", {})
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    asyncio.run(main())



