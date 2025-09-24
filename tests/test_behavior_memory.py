from __future__ import annotations

from vei.behavior.memory import MemoryStore


def test_memory_store_remember_and_recall(tmp_path) -> None:
    store = MemoryStore(path=tmp_path / "memory.db")
    store.remember(kind="vendor", key="macrocompute", value="$3199")
    store.remember(kind="vendor", key="macrocompute", value="$3299")

    values = store.recall(kind="vendor", key="macrocompute", limit=2)
    assert "$3199" in values and "$3299" in values

    all_values = [row[2] for row in store.all("vendor")]
    assert "$3299" in all_values
    store.close()
