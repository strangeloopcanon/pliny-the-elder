from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..models import BaseEvent


def load_docs(path: str | Path) -> List[BaseEvent]:
    base = Path(path)
    events: List[BaseEvent] = []
    for file in sorted(base.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        time_ms = int(data.get("time_ms", 0))
        doc_id = data.get("doc_id", file.stem)
        events.append(
            BaseEvent(
                time_ms=time_ms,
                actor_id="system",
                channel="docs",
                type="update",
                payload={
                    "doc_id": doc_id,
                    "title": data.get("title", ""),
                    "body": data.get("body", ""),
                },
            )
        )
    return sorted(events, key=lambda e: e.time_ms)
