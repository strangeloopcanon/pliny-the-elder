from __future__ import annotations

from typing import Callable, Iterable, List

from vei.behavior.policy import ScriptedProcurementPolicy
from vei.data.models import BaseEvent, VEIDataset
from vei.router.core import Router


def rollout_procurement(
    episodes: int,
    seed: int,
) -> VEIDataset:
    events: List[BaseEvent] = []
    for idx in range(max(1, episodes)):
        router_seed = seed + idx
        router = Router(seed=router_seed, artifacts_dir=None)
        runner = ScriptedProcurementPolicy(router)
        runner.run()
        events.extend(_events_from_trace(router))
    return VEIDataset(events=sorted(events, key=lambda e: e.time_ms))


def _events_from_trace(router: Router) -> Iterable[BaseEvent]:
    for entry in router.trace.entries:
        time_ms = int(entry.get("time_ms", router.bus.clock_ms))
        if entry.get("type") == "event":
            target = str(entry.get("target", "router"))
            payload = entry.get("payload", {})
            yield BaseEvent(
                time_ms=time_ms,
                actor_id="system",
                channel=target,
                type="event",
                payload={"payload": payload, "emitted": entry.get("emitted")},
            )
        elif entry.get("type") == "call":
            tool = str(entry.get("tool", "tool"))
            yield BaseEvent(
                time_ms=time_ms,
                actor_id="agent",
                channel="tool",
                type=tool,
                payload={"args": entry.get("args", {}), "response": entry.get("response")},
            )
