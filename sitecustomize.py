from __future__ import annotations

import os
import threading
import time


def _maybe_start_sse_server() -> None:
    # Opt-out switch
    if os.environ.get("VEI_DISABLE_AUTOSTART") == "1":
        return

    # Only start once per process
    if getattr(_maybe_start_sse_server, "_started", False):
        return
    setattr(_maybe_start_sse_server, "_started", True)

    try:
        from vei.router.core import Router
        from vei.router.server_fastmcp import create_mcp_server
    except Exception:
        return

    host = os.environ.get("VEI_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("VEI_PORT", "3001"))
    except ValueError:
        port = 3001

    # Try to detect if something already listens on host:port to avoid duplicate servers
    def _port_in_use(h: str, p: int) -> bool:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((h, p)) == 0
            except Exception:
                return False

    if _port_in_use(host, port):
        return

    def _run() -> None:
        # Seed/artifacts dir are read here; TraceLogger picks up artifacts dir updates later if needed
        seed = int(os.environ.get("VEI_SEED", "42042"))
        art = os.environ.get("VEI_ARTIFACTS_DIR")
        router = Router(seed=seed, artifacts_dir=art)
        srv = create_mcp_server(router)
        # Run SSE server; defaults expose /sse and /messages/
        try:
            srv.run("sse")
        except Exception:
            # Do not crash the main process if server fails to start
            pass

    t = threading.Thread(target=_run, name="vei-sse", daemon=True)
    t.start()
    # Give the server a brief moment to bind to the port to reduce flakiness
    time.sleep(0.1)


_maybe_start_sse_server()

