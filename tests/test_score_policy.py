from __future__ import annotations

import json
from pathlib import Path

from vei.score_core import compute_score


def write_trace(dirpath: Path, records: list[dict]) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_compute_score_promotes_monitor_to_policy(tmp_path: Path) -> None:
    art = tmp_path / "run"
    records = [
        {"type": "call", "tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Please approve"}, "response": {"ts": "2"}, "time_ms": 1000},
    ]
    write_trace(art, records)

    score = compute_score(art)
    policy = score.get("policy", {})
    assert policy.get("warning_count", 0) >= 1
    codes = {f["code"] for f in policy.get("findings", [])}
    assert "slack.approval_missing_amount" in codes
