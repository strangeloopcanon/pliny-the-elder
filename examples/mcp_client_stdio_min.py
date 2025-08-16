from __future__ import annotations

import asyncio
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main() -> None:
    env = os.environ.copy()
    env["VEI_DISABLE_AUTOSTART"] = "1"  # keep child stdio clean
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("VEI_SEED", "42042")
    env.setdefault("VEI_ARTIFACTS_DIR", "./_vei_out/run_stdio")

    py = sys.executable or "python3"
    print(f"Spawning child: {py} -m vei.router")
    params = StdioServerParameters(command=py, args=["-m", "vei.router"], env=env)
    try:
        import sys as _sys
        async with stdio_client(params, errlog=_sys.stderr) as (read, write):
            async with ClientSession(read, write) as s:
                print("Calling session.initialize()…")
                await asyncio.wait_for(s.initialize(), timeout=20)
                print("Initialized OK.")
                obs = await s.call_tool("vei.observe", {})
            print("First observation:", obs)
    except Exception as e:
        print(f"Handshake failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
