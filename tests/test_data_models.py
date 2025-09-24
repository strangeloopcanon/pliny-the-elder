from __future__ import annotations

import json

from vei.cli.vei_pack import slack as pack_slack
from vei.data.anonymize import pseudonymize_email, pseudonymize_name, redact_numeric_sequences
from vei.data.ingest.slack_export import load_slack_export
from vei.data.ingest.mail_dir import load_mail_dir
from vei.data.ingest.docs_dir import load_docs
from vei.data.ingest.tickets_dir import load_tickets
from vei.data.models import VEIDataset, BaseEvent


def test_pseudonymization_consistent() -> None:
    email = pseudonymize_email("alice@example.com", salt="seed")
    email2 = pseudonymize_email("alice@example.com", salt="seed")
    assert email == email2
    assert email.endswith(".example")

    name = pseudonymize_name("Alice", salt="seed")
    assert name.startswith("User-")

    redacted = redact_numeric_sequences("Account 1234567890")
    assert "7890" not in redacted


def test_dataset_model_roundtrip() -> None:
    events = [
        BaseEvent(time_ms=1, actor_id="user", channel="slack", type="message", payload={"text": "hi"}),
        BaseEvent(time_ms=2, actor_id="user", channel="mail", type="sent", payload={"subj": "Quote"}),
    ]
    dataset = VEIDataset(events=events)
    parsed = VEIDataset.model_validate(dataset.model_dump())
    assert len(parsed.events) == 2


def test_slack_ingest(tmp_path) -> None:
    export = tmp_path / "channel"
    export.mkdir()
    (export / "0001.json").write_text('[{"ts": "1.0", "text": "Hello", "user": "alice"}]', encoding="utf-8")
    records = load_slack_export(export, channel="#general", actor="alice")
    assert records[0].payload["channel"] == "#general"


def test_load_mail_dir(tmp_path) -> None:
    mail_dir = tmp_path / "mail"
    mail_dir.mkdir()
    (mail_dir / "001.json").write_text(
        json.dumps({"time_ms": 2000, "from": "bob@example.com", "subject": "Quote", "body": "Price"}),
        encoding="utf-8",
    )
    events = load_mail_dir(mail_dir)
    assert events[0].channel == "mail"
    assert events[0].payload["subj"] == "Quote"


def test_load_docs(tmp_path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "001.json").write_text(
        json.dumps({"time_ms": 3000, "doc_id": "DOC-7", "title": "Policy", "body": "Content"}),
        encoding="utf-8",
    )
    events = load_docs(docs_dir)
    assert events[0].channel == "docs"
    assert events[0].payload["title"] == "Policy"


def test_load_tickets(tmp_path) -> None:
    ticket_dir = tmp_path / "tickets"
    ticket_dir.mkdir()
    (ticket_dir / "001.json").write_text(
        json.dumps({"time_ms": 4000, "id": "TCK-1", "status": "closed", "note": "Resolved"}),
        encoding="utf-8",
    )
    events = load_tickets(ticket_dir)
    assert events[0].channel == "tickets"
    assert events[0].payload["status"] == "closed"


def test_vei_pack_slack_cli(tmp_path) -> None:
    export = tmp_path / "channel"
    export.mkdir()
    (export / "0001.json").write_text('[{"ts": "1.0", "text": "Hello", "user": "alice"}]', encoding="utf-8")
    output = tmp_path / "dataset.json"
    pack_slack(export_path=str(export), channel="#general", actor="alice", output=str(output))
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["events"][0]["channel"] == "slack"
