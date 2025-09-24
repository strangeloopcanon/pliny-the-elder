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
    state_dir: Optional[str] = None
    fault_profile: str = "off"
    drift_seed: Optional[int] = None
    drift_mode: str = "off"
    monitors: Optional[str] = None
    scenario_pack: Optional[str] = None
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
        state_dir = os.environ.get("VEI_STATE_DIR")
        fault_profile = os.environ.get("VEI_FAULT_PROFILE", "off")
        drift_seed_raw = os.environ.get("VEI_DRIFT_SEED")
        drift_mode = os.environ.get("VEI_DRIFT_MODE") or os.environ.get("VEI_DRIFT_RATE") or "off"
        monitors = os.environ.get("VEI_MONITORS")
        scenario_pack = os.environ.get("VEI_SCENARIO_PACK")

        drift_seed: Optional[int]
        if drift_seed_raw is None:
            drift_seed = None
        else:
            try:
                drift_seed = int(drift_seed_raw)
            except ValueError:
                drift_seed = None

        # Prefer new dynamic scenario loader driven by env vars
        scenario = load_from_env(seed)

        return cls(
            host=host,
            port=port,
            seed=seed,
            artifacts_dir=artifacts_dir,
            state_dir=state_dir,
            fault_profile=fault_profile,
            drift_seed=drift_seed,
            drift_mode=drift_mode,
            monitors=monitors,
            scenario_pack=scenario_pack,
            scenario=scenario,
        )
