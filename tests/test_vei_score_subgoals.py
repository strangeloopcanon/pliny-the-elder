from __future__ import annotations

import json
from pathlib import Path

import typer.testing
from vei.cli.vei_score import score as score_cmd


def run_score(artifacts_dir: Path) -> dict:
    runner = typer.testing.CliRunner()
    result = runner.invoke(score_cmd, ["--artifacts-dir", str(artifacts_dir)])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def write_trace(dirpath: Path, records: list[dict]) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "trace.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_score_citations_triggered_by_browser_read(tmp_path: Path):
    art = tmp_path / "citations"
    records = [
        {"type": "call", "tool": "browser.read", "args": {}, "response": {"url": "u", "title": "t"}},
    ]
    write_trace(art, records)
    data = run_score(art)
    assert data["subgoals"]["citations"] == 1
    # No email parsed in this trace, so success should be False
    assert data["success"] is False


def test_score_approval_detected_via_emoji(tmp_path: Path):
    art = tmp_path / "approval_emoji"
    records = [
        {"type": "event", "target": "slack", "payload": {"text": ":white_check_mark: Approved"}},
    ]
    write_trace(art, records)
    data = run_score(art)
    assert data["subgoals"]["approval"] == 1
    # Email parsing still not present
    assert data["success"] is False


def test_score_approval_detected_via_text_only(tmp_path: Path):
    art = tmp_path / "approval_text"
    records = [
        {"type": "event", "target": "slack", "payload": {"text": "Approved, proceed."}},
    ]
    write_trace(art, records)
    data = run_score(art)
    assert data["subgoals"]["approval"] == 1
    assert data["success"] is False


def test_score_no_approval_for_irrelevant_slack(tmp_path: Path):
    art = tmp_path / "no_approval"
    records = [
        {"type": "event", "target": "slack", "payload": {"text": "What is the budget amount?"}},
    ]
    write_trace(art, records)
    data = run_score(art)
    assert data["subgoals"]["approval"] == 0
    assert data["success"] is False

