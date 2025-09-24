from __future__ import annotations

from vei.world.compiler import compile_scene


def test_compile_scene_renders_synthetic_assets() -> None:
    spec = {
        "meta": {"name": "demo", "description": "Procurement flow"},
        "budget": {"cap_usd": 3300, "approval_threshold": 1500},
        "slack": {"initial_message": "Remember to cite sources", "derail_prob": 0.05},
        "vendors": [
            {
                "name": "MacroCompute",
                "price": [3100, 3200],
                "eta_days": [3, 5],
                "templates": ["{vendor} quote ${price}, ETA {eta} days"],
            }
        ],
        "participants": [
            {"participant_id": "approver", "name": "Sam", "role": "manager", "email": "sam@example.com"}
        ],
        "documents": [
            {"doc_id": "DOC-1", "title": "Budget Policy", "body": "All purchases need approval.", "tags": ["policy"]}
        ],
        "calendar_events": [
            {
                "event_id": "EVT-1",
                "title": "Kickoff",
                "start_ms": 10_000,
                "end_ms": 11_000,
                "attendees": ["sam@example.com"],
            }
        ],
        "tickets": [
            {"ticket_id": "TCK-1", "title": "Laptop approval", "status": "open", "assignee": "approver"}
        ],
        "triggers": [
            {"at_ms": 5_000, "target": "slack", "payload": {"text": "Reminder"}},
        ],
    }

    scenario = compile_scene(spec, seed=123)

    assert scenario.budget_cap_usd == 3300
    assert scenario.derail_prob == 0.05
    assert scenario.slack_initial_message.startswith("Remember")
    assert scenario.vendor_reply_variants and "MacroCompute" in scenario.vendor_reply_variants[0]

    assert scenario.participants and scenario.participants[0].participant_id == "approver"
    assert scenario.documents and "DOC-1" in scenario.documents
    assert scenario.documents["DOC-1"].title == "Budget Policy"

    assert scenario.calendar_events and scenario.calendar_events[0].event_id == "EVT-1"
    assert scenario.tickets and scenario.tickets["TCK-1"].status == "open"

    assert scenario.metadata and scenario.metadata["name"] == "demo"
    assert scenario.triggers and scenario.triggers[0]["target"] == "slack"
