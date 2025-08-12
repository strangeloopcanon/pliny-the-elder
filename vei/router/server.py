from __future__ import annotations

import json
import os
import sys
from typing import Any

from .core import Router, MCPError


def jsonrpc_loop(router: Router) -> None:
    # Extremely small JSON-RPC 2.0 handler over stdio
    for line in sys.stdin:
        try:
            req = json.loads(line)
            method = req.get("method")
            params = req.get("params", {})
            if method == "mcp.call":
                tool = params["tool"]
                args = params.get("args", {})
                try:
                    if tool == "vei.observe":
                        res = router.observe(focus_hint=args.get("focus")).model_dump()
                    else:
                        res = router.call_and_step(tool, args)
                    resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": res}
                except MCPError as e:
                    resp = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": e.code, "message": e.message}}
            elif method == "mcp.list_tools":
                tools = [
                    "slack.list_channels",
                    "slack.open_channel",
                    "slack.send_message",
                    "slack.react",
                    "slack.fetch_thread",
                    "mail.list",
                    "mail.open",
                    "mail.compose",
                    "mail.reply",
                    "browser.open",
                    "browser.find",
                    "browser.click",
                    "browser.type",
                    "browser.submit",
                    "browser.read",
                    "browser.back",
                ]
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": tools}
            else:
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "Method not found"}}
        except Exception as e:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main() -> None:
    seed = int(os.environ.get("VEI_SEED", "42042"))
    art = os.environ.get("VEI_ARTIFACTS_DIR")
    router = Router(seed=seed, artifacts_dir=art)
    try:
        jsonrpc_loop(router)
    finally:
        router.trace.flush()


if __name__ == "__main__":
    main()
