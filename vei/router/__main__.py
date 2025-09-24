from __future__ import annotations

import os

from .core import Router
from .server_fastmcp import create_mcp_server
from vei.config import Config


def main() -> None:
    cfg = Config.from_env()
    router = Router(seed=cfg.seed, artifacts_dir=cfg.artifacts_dir, scenario=cfg.scenario)
    server = create_mcp_server(router, host=cfg.host, port=cfg.port)
    server.run("stdio")


if __name__ == "__main__":
    main()
