from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..models import BaseEvent


def load_tickets(path: str | Path) -> List[BaseEvent]:
    base = Path(path)
    events: List[BaseEvent] = []
    for file in sorted(base.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        time_ms = int(data.get("time_ms", 0))
        ticket_id = data.get("id", "TCK-0")
        events.append(
            BaseEvent(
                time_ms=time_ms,
                actor_id="system",
                channel="tickets",
                type="update",
                payload={
                    "ticket_id": ticket_id,
                    "status": data.get("status", "open"),
                    "note": data.get("note", ""),
                },
            )
        )
    return sorted(events, key=lambda e: e.time_ms)
