from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_rl_train_runs(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    cmd = [
        sys.executable,
        "examples/rl_train.py",
        "--episodes",
        "1",
        "--max-steps",
        "2",
        "--out-dir",
        str(out_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (out_dir / "trace.jsonl").exists()
