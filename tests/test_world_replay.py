from __future__ import annotations

import json

from vei.router.core import Router


def test_replay_adapter_schedules_events(tmp_path, monkeypatch) -> None:
    dataset = {
        "metadata": {"name": "demo"},
        "events": [
            {
                "time_ms": 1000,
                "actor_id": "user",
                "channel": "slack",
                "type": "message",
                "payload": {"text": "hello"},
            },
            {
                "time_ms": 1500,
                "actor_id": "user",
                "channel": "mail",
                "type": "received",
                "payload": {"body_text": "price"},
            },
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    monkeypatch.setenv("VEI_DATASET", str(path))

    router = Router(seed=1, artifacts_dir=None)
    pending = router.pending()
    assert pending.get("slack", 0) >= 1
    assert pending.get("mail", 0) >= 1
    monkeypatch.delenv("VEI_DATASET", raising=False)
