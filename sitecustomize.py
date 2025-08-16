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
        from vei.config import Config
    except Exception as e:
        # Import-time failure; nothing we can do. Optionally log for debugging.
        _log_path = os.environ.get("VEI_SSE_LOG_FILE", os.path.join(os.getcwd(), "_vei_out", "sse_autostart.log"))
        try:
            os.makedirs(os.path.dirname(_log_path), exist_ok=True)
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(f"[import-error] {e}\n")
        except Exception:
            ...
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
        # Read full configuration (host/port/seed/artifacts/scenario) from env
        cfg = Config.from_env()
        router = Router(seed=cfg.seed, artifacts_dir=cfg.artifacts_dir, scenario=cfg.scenario)
        srv = create_mcp_server(router, host=cfg.host, port=cfg.port)
        # Run SSE server; defaults expose /sse and /messages/
        try:
            srv.run("sse")
        except Exception as e:
            # Do not crash the main process if server fails to start, but log why
            _log_path = os.environ.get("VEI_SSE_LOG_FILE", os.path.join(os.getcwd(), "_vei_out", "sse_autostart.log"))
            try:
                os.makedirs(os.path.dirname(_log_path), exist_ok=True)
                with open(_log_path, "a", encoding="utf-8") as _f:
                    _f.write(f"[run-error] {type(e).__name__}: {e}\n")
            except Exception:
                ...

    t = threading.Thread(target=_run, name="vei-sse", daemon=True)
    t.start()
    # Give the server a brief moment to bind to the port to reduce flakiness
    time.sleep(0.1)


_maybe_start_sse_server()
