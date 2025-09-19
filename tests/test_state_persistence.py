from __future__ import annotations

from pathlib import Path

import os

from vei.router.core import Router
from vei.world.state import Event, StateStore


def test_state_store_persists_and_recovers(tmp_path: Path) -> None:
    base = tmp_path / "state"
    store = StateStore(base_dir=base, branch="alpha")

    def reducer(state: dict[str, object], event: Event) -> None:
        state["total"] = state.get("total", 0) + int(event.payload.get("value", 0))

    store.register_reducer("add", reducer)
    store.append("add", {"value": 3})
    snap = store.take_snapshot()

    events_path = base / "alpha" / "events.jsonl"
    snapshot_path = base / "alpha" / "snapshots" / f"{snap.index:09d}.json"
    assert events_path.exists()
    assert snapshot_path.exists()

    reloaded = StateStore(base_dir=base, branch="alpha")
    reloaded.register_reducer("add", reducer)
    assert reloaded.head == 0
    assert reloaded.materialised_state()["total"] == 3


def test_router_writes_receipts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEI_STATE_DIR", str(tmp_path / "state"))
    router = Router(seed=42, artifacts_dir=None)
    router.call_and_step("browser.read", {})

    receipts_path = Path(os.environ["VEI_STATE_DIR"]) / "main" / "receipts.jsonl"
    assert receipts_path.exists()
    content = receipts_path.read_text(encoding="utf-8").strip()
    assert "browser.read" in content

    monkeypatch.delenv("VEI_STATE_DIR", raising=False)
