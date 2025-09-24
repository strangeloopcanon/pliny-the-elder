from __future__ import annotations

from typing import Dict, List, Optional

from vei.world.scenario import CalendarEvent, Scenario


class CalendarSim:
    """Synthetic calendar twin supporting deterministic interactions."""

    def __init__(self, scenario: Optional[Scenario] = None):
        self.events: Dict[str, CalendarEvent] = {}
        self.responses: Dict[str, Dict[str, str]] = {}
        if scenario and scenario.calendar_events:
            for event in scenario.calendar_events:
                self.events[event.event_id] = event
                self.responses[event.event_id] = {}
        self._event_seq = self._init_seq()

    def list_events(self) -> List[Dict[str, object]]:
        return [self._event_payload(evt) for evt in sorted(self.events.values(), key=lambda e: e.start_ms)]

    def create_event(
        self,
        title: str,
        start_ms: int,
        end_ms: int,
        attendees: Optional[List[str]] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, object]:
        event_id = f"EVT-{self._event_seq}"
        self._event_seq += 1
        evt = CalendarEvent(
            event_id=event_id,
            title=title,
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            attendees=attendees or None,
            location=location,
            description=description,
        )
        self.events[event_id] = evt
        self.responses[event_id] = {}
        return {"event_id": event_id}

    def accept(self, event_id: str, attendee: str) -> Dict[str, object]:
        return self._respond(event_id, attendee, "accepted")

    def decline(self, event_id: str, attendee: str) -> Dict[str, object]:
        return self._respond(event_id, attendee, "declined")

    def _respond(self, event_id: str, attendee: str, status: str) -> Dict[str, object]:
        evt = self.events.get(event_id)
        if not evt:
            raise ValueError(f"unknown event: {event_id}")
        if attendee and evt.attendees and attendee not in evt.attendees:
            raise ValueError(f"attendee {attendee} not on event {event_id}")
        self.responses.setdefault(event_id, {})[attendee] = status
        return {"event_id": event_id, "attendee": attendee, "status": status}

    def _event_payload(self, evt: CalendarEvent) -> Dict[str, object]:
        return {
            "event_id": evt.event_id,
            "title": evt.title,
            "start_ms": evt.start_ms,
            "end_ms": evt.end_ms,
            "attendees": list(evt.attendees or []),
            "location": evt.location,
            "description": evt.description,
            "responses": dict(self.responses.get(evt.event_id, {})),
        }

    def _init_seq(self) -> int:
        seq = 1
        for event_id in self.events.keys():
            try:
                if event_id.startswith("EVT-"):
                    seq = max(seq, int(event_id.split("-", 1)[1]) + 1)
            except ValueError:
                continue
        return seq

