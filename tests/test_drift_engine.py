from __future__ import annotations

from vei.router.core import Router


def test_drift_schedules_and_repeats(monkeypatch) -> None:
    monkeypatch.setenv("VEI_DRIFT_MODE", "fast")
    monkeypatch.setenv("VEI_DRIFT_SEED", "4242")

    router = Router(seed=101, artifacts_dir=None)

    state = router.state_store.materialised_state()
    drift_state = state.get("drift", {})
    assert drift_state.get("scheduled"), "drift schedules should be recorded when enabled"

    # Advance time to ensure at least one drift event fires.
    router.tick(120000)
    state_after = router.state_store.materialised_state()
    delivered = state_after.get("drift", {}).get("delivered", {})
    assert any(count >= 1 for count in delivered.values())

    # Ensure subsequent scheduling keeps the queue populated.
    router.tick(200000)
    later_state = router.state_store.materialised_state()
    later_scheduled = later_state.get("drift", {}).get("scheduled", [])
    assert len(later_scheduled) > len(drift_state.get("scheduled", []))

    # Clean up env vars for other tests.
    monkeypatch.delenv("VEI_DRIFT_MODE", raising=False)
    monkeypatch.delenv("VEI_DRIFT_SEED", raising=False)
