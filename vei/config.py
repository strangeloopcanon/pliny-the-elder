from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from vei.world.scenario import Scenario
from vei.world.scenarios import load_from_env


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 3001
    seed: int = 42042
    artifacts_dir: Optional[str] = None
    scenario: Optional[Scenario] = None

    @classmethod
    def from_env(cls) -> "Config":
        host = os.environ.get("VEI_HOST", "127.0.0.1")
        try:
            port = int(os.environ.get("VEI_PORT", "3001"))
        except ValueError:
            port = 3001
        try:
            seed = int(os.environ.get("VEI_SEED", "42042"))
        except ValueError:
            seed = 42042
        artifacts_dir = os.environ.get("VEI_ARTIFACTS_DIR")

        # Prefer new dynamic scenario loader driven by env vars
        scenario = load_from_env(seed)

        return cls(host=host, port=port, seed=seed, artifacts_dir=artifacts_dir, scenario=scenario)
