from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from ..models import BaseEvent
from ..anonymize import pseudonymize_email


def load_slack_export(path: str | Path, *, channel: str, actor: str) -> List[BaseEvent]:
    base_path = Path(path)
    records: List[BaseEvent] = []
    for item in sorted(base_path.glob("*.json")):
        data = json.loads(item.read_text(encoding="utf-8"))
        for msg in data:
            ts_ms = int(float(msg.get("ts", "0")) * 1000)
            text = msg.get("text", "")
            user = msg.get("user", "user")
            email = pseudonymize_email(f"{user}@slack.local")
            records.append(
                BaseEvent(
                    time_ms=ts_ms,
                    actor_id=email,
                    channel="slack",
                    type="message",
                    payload={
                        "channel": channel,
                        "text": text,
                        "user": email,
                        "original_user": user,
                    },
                )
            )
            thread_ts = msg.get("thread_ts")
            if thread_ts:
                records.append(
                    BaseEvent(
                        time_ms=ts_ms + 1,
                        actor_id=email,
                        channel="slack",
                        type="thread",
                        payload={"channel": channel, "thread_ts": thread_ts, "text": text},
                    )
                )
    return sorted(records, key=lambda e: e.time_ms)
