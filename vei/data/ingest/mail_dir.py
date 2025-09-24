from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..anonymize import pseudonymize_email
from ..models import BaseEvent


def load_mail_dir(path: str | Path, *, folder: str = "INBOX") -> List[BaseEvent]:
    base = Path(path)
    events: List[BaseEvent] = []
    for file in sorted(base.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        time_ms = int(data.get("time_ms", 0))
        sender = pseudonymize_email(data.get("from", "sender@example.com"))
        events.append(
            BaseEvent(
                time_ms=time_ms,
                actor_id=sender,
                channel="mail",
                type="received",
                payload={
                    "folder": folder,
                    "from": sender,
                    "subj": data.get("subject", ""),
                    "body_text": data.get("body", ""),
                },
            )
        )
    return sorted(events, key=lambda e: e.time_ms)
