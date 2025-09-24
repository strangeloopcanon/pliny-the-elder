from __future__ import annotations

from typing import Iterable

from vei.data.models import BaseEvent
from vei.router.core import EventBus


class ReplayAdapter:
    def __init__(self, bus: EventBus, events: Iterable[BaseEvent]) -> None:
        self.bus = bus
        self.events = sorted(events, key=lambda e: e.time_ms)
        self._index = 0

    def prime(self) -> None:
        for event in self.events:
            dt = max(0, event.time_ms - self.bus.clock_ms)
            payload = {"dataset": event.channel, "data": event.payload}
            self.bus.schedule(dt_ms=dt, target=event.channel, payload=payload)
