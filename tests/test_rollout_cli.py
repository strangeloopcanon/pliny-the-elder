from __future__ import annotations

import json
from pathlib import Path

from vei.cli.vei_rollout import procurement


def test_rollout_cli_procurement(tmp_path: Path) -> None:
    output = tmp_path / "rollout.json"
    procurement(episodes=1, seed=123, output=output)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["events"], "expected events in rollout dataset"
