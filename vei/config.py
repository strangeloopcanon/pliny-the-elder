from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from vei.world.scenario import Scenario
from vei.world.scenarios import get_scenario


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

        scenario: Optional[Scenario] = None
        scen_name = os.environ.get("VEI_SCENARIO_NAME")
        scen_file = os.environ.get("VEI_SCENARIO_FILE")
        scen_json = os.environ.get("VEI_SCENARIO_JSON")
        try:
            if scen_name:
                scenario = get_scenario(scen_name)
            elif scen_file and os.path.exists(scen_file):
                with open(scen_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                scenario = Scenario(**data)
            elif scen_json:
                scenario = Scenario(**json.loads(scen_json))
        except Exception:
            scenario = None

        return cls(host=host, port=port, seed=seed, artifacts_dir=artifacts_dir, scenario=scenario)

