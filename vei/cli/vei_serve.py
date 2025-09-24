from __future__ import annotations

import os
import typer

from vei.router.core import Router
from vei.router.server_fastmcp import create_mcp_server
from vei.config import Config

app = typer.Typer(add_completion=False)


@app.command()
def serve(
    host: str = typer.Option(None, help="Host to bind (default VEI_HOST or 127.0.0.1)"),
    port: int = typer.Option(None, help="Port to bind (default VEI_PORT or 3001)"),
    seed: int = typer.Option(None, help="Deterministic seed (default VEI_SEED or 42042)"),
    artifacts_dir: str = typer.Option(None, help="Artifacts dir for trace.jsonl (default VEI_ARTIFACTS_DIR)"),
    alias_packs: str = typer.Option("xero", help="CSV of ERP alias packs: xero,netsuite,dynamics,quickbooks"),
    crm_alias_packs: str = typer.Option("hubspot", help="CSV of CRM alias packs: hubspot,salesforce"),
    erp_error_rate: float = typer.Option(0.0, help="Deterministic ERP error rate (0.0..1.0). No latency injected."),
    crm_error_rate: float = typer.Option(0.0, help="Deterministic CRM error rate (0.0..1.0). No latency injected."),
) -> None:
    # Bind env to leverage existing server configuration
    if alias_packs:
        os.environ["VEI_ALIAS_PACKS"] = alias_packs
    if crm_alias_packs:
        os.environ["VEI_CRM_ALIAS_PACKS"] = crm_alias_packs
    os.environ["VEI_ERP_ERROR_RATE"] = str(erp_error_rate)
    os.environ["VEI_CRM_ERROR_RATE"] = str(crm_error_rate)

    cfg = Config.from_env()
    if host:
        cfg.host = host
    if port is not None:
        cfg.port = port
    if seed is not None:
        cfg.seed = seed
    if artifacts_dir:
        cfg.artifacts_dir = artifacts_dir

    router = Router(seed=cfg.seed, artifacts_dir=cfg.artifacts_dir, scenario=cfg.scenario)
    server = create_mcp_server(router, host=cfg.host, port=cfg.port)
    server.run("sse")


if __name__ == "__main__":
    app()
