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
                    elif tool == "vei.tick":
                        dt = int(args.get("dt_ms", 1000))
                        res = router.tick(dt)
                    elif tool == "vei.pending":
                        res = router.pending()
                    elif tool == "vei.act_and_observe":
                        t = args.get("tool")
                        a = args.get("args", {})
                        if not isinstance(a, dict):
                            a = {}
                        res = router.act_and_observe(tool=t, args=a)
                    elif tool == "vei.reset":
                        # Reinitialize the router deterministically
                        try:
                            seed = int(args.get("seed")) if "seed" in args else int(os.environ.get("VEI_SEED", "42042"))
                        except Exception:
                            seed = int(os.environ.get("VEI_SEED", "42042"))
                        old = router
                        router = Router(seed=seed, artifacts_dir=old.trace.out_dir, scenario=old.scenario)
                        res = {"ok": True, "seed": seed, "time_ms": router.bus.clock_ms}
                    elif tool == "vei.help":
                        # Return usage guidance and tool catalog similar to FastMCP server
                        res = {
                            "instructions": (
                                "Use MCP tools to interact with the VEI environment. Typical loop: "
                                "(1) call vei.observe {} to obtain an observation with an action_menu and pending_events; "
                                "(2) choose exactly one tool to call (often from action_menu) then call vei.observe {}; "
                                "or simply call vei.act_and_observe {tool,args} to do both in one step; (3) repeat."
                            ),
                            "tools": [
                                {"tool": "vei.observe", "args": {"focus": "browser|slack|mail?"}},
                                {"tool": "vei.act_and_observe", "args": {"tool": "str", "args": "object"}},
                                {"tool": "vei.tick", "args": {"dt_ms": "int?"}},
                                {"tool": "vei.pending", "args": {}},
                                {"tool": "vei.reset", "args": {"seed": "int?"}},
                                {"tool": "browser.read", "args": {}},
                                {"tool": "browser.find", "args": {"query": "str", "top_k": "int?"}},
                                {"tool": "browser.click", "args": {"node_id": "str"}},
                                {"tool": "browser.open", "args": {"url": "str"}},
                                {"tool": "browser.type", "args": {"node_id": "str", "text": "str"}},
                                {"tool": "browser.submit", "args": {"form_id": "str"}},
                                {"tool": "browser.back", "args": {}},
                                {"tool": "slack.list_channels", "args": {}},
                                {"tool": "slack.open_channel", "args": {"channel": "str"}},
                                {"tool": "slack.send_message", "args": {"channel": "str", "text": "str", "thread_ts": "str?"}},
                                {"tool": "slack.react", "args": {"channel": "str", "ts": "str", "emoji": "str"}},
                                {"tool": "slack.fetch_thread", "args": {"channel": "str", "thread_ts": "str"}},
                                {"tool": "mail.list", "args": {"folder": "str?"}},
                                {"tool": "mail.open", "args": {"id": "str"}},
                                {"tool": "mail.compose", "args": {"to": "str", "subj": "str", "body_text": "str"}},
                                {"tool": "mail.reply", "args": {"id": "str", "body_text": "str"}},
                            ],
                            "examples": [
                                {"tool": "vei.observe", "args": {}},
                                {"tool": "browser.read", "args": {}},
                                {"tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Summary: budget $3200, citations included."}},
                                {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."}},
                            ],
                        }
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
                    # VEI helpers for loop control and discovery
                    "vei.observe",
                    "vei.tick",
                    "vei.pending",
                    "vei.reset",
                    "vei.act_and_observe",
                    "vei.help",
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
