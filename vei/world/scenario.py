from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Participant:
    """Metadata describing an actor in the scenario (humans, systems)."""

    participant_id: str
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    slack: Optional[str] = None


@dataclass
class Document:
    """Synthetic document stored in the docs twin."""

    doc_id: str
    title: str
    body: str
    tags: Optional[List[str]] = None


@dataclass
class CalendarEvent:
    """Calendar entry that can be exposed via calendar tools."""

    event_id: str
    title: str
    start_ms: int
    end_ms: int
    attendees: Optional[List[str]] = None
    location: Optional[str] = None
    description: Optional[str] = None


@dataclass
class Ticket:
    """Ticket/work item tracked by the tickets twin."""

    ticket_id: str
    title: str
    status: str
    assignee: Optional[str] = None
    description: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None


@dataclass
class Scenario:
    # Slack configuration
    budget_cap_usd: Optional[int] = None
    derail_prob: Optional[float] = None
    slack_initial_message: Optional[str] = None

    # Mail configuration
    vendor_reply_variants: Optional[List[str]] = None

    # Browser configuration
    browser_nodes: Optional[Dict[str, dict]] = None

    # Optional pre-scheduled events (e.g., derailments)
    derail_events: Optional[List[Dict[str, Any]]] = None

    # Additional synthetic world assets
    participants: Optional[List[Participant]] = None
    documents: Optional[Dict[str, Document]] = None
    calendar_events: Optional[List[CalendarEvent]] = None
    tickets: Optional[Dict[str, Ticket]] = None
    triggers: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
