from __future__ import annotations

from pathlib import Path

from vei.world.state import Event, StateStore


def test_append_and_head_updates() -> None:
    store = StateStore()
    assert store.head == -1

    first = store.append("init", {"foo": 1}, clock_ms=100)
    assert store.head == first.index == 0
    assert first.clock_ms == 100

    second = store.append("mutate", {"bar": 2})
    assert store.head == second.index == 1
    assert list(evt.kind for evt in store.events) == ["init", "mutate"]


def test_snapshot_and_branch_are_isolated(tmp_path: Path) -> None:
    store = StateStore(base_dir=tmp_path)
    store.append("init", {"foo": 1}, reducer=lambda state: state.__setitem__("foo", 1))
    snap = store.take_snapshot()

    branched = store.branch_from(snap, branch="dev")
    branched.append("mutate", {"foo": 2}, reducer=lambda state: state.__setitem__("foo", 2))

    # Original store remains unchanged.
    assert store.materialised_state()["foo"] == 1
    assert branched.materialised_state()["foo"] == 2


def test_rebuild_state_uses_registered_reducers() -> None:
    store = StateStore()

    def apply_init(state: dict[str, object], event: Event) -> None:
        state["items"] = [event.payload["value"]]

    def apply_add(state: dict[str, object], event: Event) -> None:
        state.setdefault("items", []).append(event.payload["value"])

    store.register_reducer("init", apply_init)
    store.register_reducer("add", apply_add)

    store.append("init", {"value": "a"})
    store.append("add", {"value": "b"})
    store.append("add", {"value": "c"})

    rebuilt = store.rebuild_state()
    assert rebuilt == {"items": ["a", "b", "c"]}

    partial = store.rebuild_state(upto=1)
    assert partial == {"items": ["a", "b"]}

