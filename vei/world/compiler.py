"""Compiler translating scene DSL specs into runtime `Scenario` objects."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .scenario import CalendarEvent, Document, Participant, Scenario, Ticket
from .scene_dsl import (
    CalendarEventSpec,
    DocumentSpec,
    ParticipantSpec,
    SceneSpec,
    TicketSpec,
    VendorSpec,
)


def load_scene_spec(payload: Any) -> SceneSpec:
    """Normalise incoming payload (dict / JSON string / path) into SceneSpec."""

    if isinstance(payload, SceneSpec):
        return payload
    if isinstance(payload, (str, Path)):
        path = Path(payload)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return SceneSpec.model_validate(data)
        try:
            data = json.loads(str(payload))
            return SceneSpec.model_validate(data)
        except json.JSONDecodeError as exc:  # noqa: F841
            raise ValueError(f"scene payload is not JSON or path: {payload}") from exc
    if isinstance(payload, dict):
        return SceneSpec.model_validate(payload)
    raise TypeError(f"unsupported scene spec payload: {type(payload)!r}")


def compile_scene(spec: SceneSpec | Dict[str, Any], seed: Optional[int] = None) -> Scenario:
    """Compile a SceneSpec into a Scenario consumable by the router."""

    scene = load_scene_spec(spec)
    rng = random.Random(seed)

    vendor_variants = _render_vendor_variants(scene.vendors, rng)
    slack_initial = scene.slack.initial_message or "Reminder: include budget details."
    derail_events = [
        {"dt_ms": trig.at_ms, "target": trig.target, "payload": dict(trig.payload)}
        for trig in scene.triggers
    ] or None

    scenario = Scenario(
        budget_cap_usd=scene.budget.cap_usd,
        derail_prob=scene.slack.derail_prob,
        slack_initial_message=slack_initial,
        vendor_reply_variants=vendor_variants or None,
        browser_nodes=scene.browser_nodes,
        derail_events=derail_events,
        participants=_build_participants(scene.participants),
        documents=_build_documents(scene.documents),
        calendar_events=_build_calendar(scene.calendar_events),
        tickets=_build_tickets(scene.tickets),
        triggers=[
            {"at_ms": trig.at_ms, "target": trig.target, "payload": dict(trig.payload)}
            for trig in scene.triggers
        ]
        or None,
        metadata={
            "name": scene.meta.name,
            "description": scene.meta.description,
            "tags": list(scene.meta.tags),
            "approval_threshold": scene.budget.approval_threshold,
        },
    )
    return scenario


def _render_vendor_variants(vendors: Iterable[VendorSpec], rng: random.Random) -> List[str]:
    variants: List[str] = []
    for vendor in vendors:
        price = _sample_number(vendor.price, rng)
        eta = int(_sample_number(vendor.eta_days, rng))
        if vendor.templates:
            template = rng.choice(vendor.templates)
            variants.append(template.format(price=int(price), eta=eta, vendor=vendor.name))
        else:
            variants.append(f"{vendor.name} quote: ${int(price)}, ETA: {eta} days.")
    return variants


def _sample_number(source: Any, rng: random.Random) -> float:
    if isinstance(source, (int, float)):
        return float(source)
    if isinstance(source, list) and len(source) == 2:
        lo, hi = source
        try:
            lo_f = float(lo)
            hi_f = float(hi)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"range bounds must be numeric: {source}") from exc
        if lo_f > hi_f:
            lo_f, hi_f = hi_f, lo_f
        return rng.uniform(lo_f, hi_f)
    if isinstance(source, list) and len(source) == 1:
        return float(source[0])
    raise ValueError(f"unsupported numeric source: {source!r}")


def _build_participants(items: Iterable[ParticipantSpec]) -> Optional[List[Participant]]:
    data = [
        Participant(
            participant_id=item.participant_id,
            name=item.name,
            role=item.role,
            email=item.email,
            slack=item.slack,
        )
        for item in items
    ]
    return data or None


def _build_documents(items: Iterable[DocumentSpec]) -> Optional[Dict[str, Document]]:
    docs = {
        item.doc_id: Document(
            doc_id=item.doc_id,
            title=item.title,
            body=item.body,
            tags=item.tags or None,
        )
        for item in items
    }
    return docs or None


def _build_calendar(items: Iterable[CalendarEventSpec]) -> Optional[List[CalendarEvent]]:
    events = [
        CalendarEvent(
            event_id=item.event_id,
            title=item.title,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            attendees=item.attendees or None,
            location=item.location,
            description=item.description,
        )
        for item in items
    ]
    return events or None


def _build_tickets(items: Iterable[TicketSpec]) -> Optional[Dict[str, Ticket]]:
    tickets = {
        item.ticket_id: Ticket(
            ticket_id=item.ticket_id,
            title=item.title,
            status=item.status,
            assignee=item.assignee,
            description=item.description,
            history=item.history or None,
        )
        for item in items
    }
    return tickets or None

