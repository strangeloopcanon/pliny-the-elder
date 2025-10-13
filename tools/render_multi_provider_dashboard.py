#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List


ENTRY_PATTERN = re.compile(r"^([A-Za-z0-9._/\-]+):$")
KV_PATTERN = re.compile(r"([A-Za-z0-9_]+)=([^\s]+)")


@dataclass
class Entry:
    run_id: str
    scenario: str
    label: str
    success: str | None = None
    actions: int | None = None
    time_ms: int | None = None
    tokens: int | None = None
    subgoals: Dict[str, int] = field(default_factory=dict)
    policy: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    top_tools: str | None = None
    path: Path | None = None


def parse_summary(summary_path: Path) -> Iterable[Entry]:
    run_dir = summary_path.parent.parent
    scenario = summary_path.parent.name
    run_id = run_dir.name
    entries: Dict[str, Entry] = {}
    current: Entry | None = None

    def parse_kvs(text: str) -> Dict[str, str]:
        return {match.group(1): match.group(2) for match in KV_PATTERN.finditer(text)}

    for raw_line in summary_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            current = None if current else current
            continue

        match = ENTRY_PATTERN.match(stripped)
        if match:
            label = match.group(1)
            entry = Entry(run_id=run_id, scenario=scenario, label=label, path=summary_path)
            entries[label] = entry
            current = entry
            continue

        if current is None:
            continue

        if stripped.startswith("Success:"):
            current.success = stripped.split(":", 1)[1].strip()
            continue

        if stripped.startswith("Actions:"):
            try:
                current.actions = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                current.actions = None
            continue

        if stripped.startswith("Subgoals:"):
            current.subgoals.update(parse_kvs(stripped[len("Subgoals:") :].strip()))
            continue

        if stripped.startswith("doc_logged="):
            current.subgoals.update(parse_kvs(stripped))
            continue

        if stripped.startswith("Time_ms:"):
            try:
                current.time_ms = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                current.time_ms = None
            continue

        if stripped.startswith("Tokens:"):
            try:
                current.tokens = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                current.tokens = None
            continue

        if stripped.startswith("Policy:"):
            current.policy.update(parse_kvs(stripped[len("Policy:") :].strip()))
            continue

        if stripped.startswith("Top tools:"):
            current.top_tools = stripped[len("Top tools:") :].strip()
            continue

        if stripped.startswith("- "):
            current.warnings.append(stripped[2:])
            continue

    return entries.values()


def gather_entries(root: Path) -> List[Entry]:
    summaries = sorted(root.glob("*/**/summary.txt"))
    entries: List[Entry] = []
    for summary in summaries:
        entries.extend(parse_summary(summary))
    return entries


def render_table(entries: Iterable[Entry]) -> str:
    header = (
        "| Run | Scenario | Entry | Success | Actions | Subgoals (cit/approval/amt/email/doc/ticket/crm) | "
        "Policy (warn/err) | Warnings |"
    )
    divider = "| --- | --- | --- | --- | ---: | --- | --- | --- |"
    lines = [header, divider]
    for entry in entries:
        if entry.label.lower().startswith("baselines"):
            continue
        if "/" not in entry.label:
            continue
        cit = entry.subgoals.get("citations", "?")
        appr = entry.subgoals.get("approval", "?")
        appr_amt = entry.subgoals.get("approval_with_amount", "?")
        email = entry.subgoals.get("email_parsed", "?")
        email_sent = entry.subgoals.get("email_sent", "?")
        doc = entry.subgoals.get("doc_logged", "?")
        ticket = entry.subgoals.get("ticket_updated", "?")
        crm = entry.subgoals.get("crm_logged", "?")
        policy_warn = entry.policy.get("warnings", entry.policy.get("warning_count", "0"))
        policy_err = entry.policy.get("errors", entry.policy.get("error_count", "0"))
        warning_preview = "; ".join(entry.warnings[:3]) if entry.warnings else ""
        lines.append(
            f"| `{entry.run_id}` | {entry.scenario} | {entry.label} | "
            f"{entry.success or ''} | {entry.actions or ''} | "
            f"{cit}/{appr}/{appr_amt}/{email_sent}/{email}/{doc}/{ticket}/{crm} | "
            f"{policy_warn}/{policy_err} | {warning_preview} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Markdown dashboard from multi-provider summaries.")
    parser.add_argument(
        "root",
        nargs="?",
        default="_vei_out/gpt5_llmtest",
        help="Root directory containing multi_provider_* runs (default: %(default)s)",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Only include entries from the latest run directory",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    entries = gather_entries(root)
    if not entries:
        raise SystemExit(f"No summary files found under {root}")

    entries.sort(key=lambda e: (e.run_id, e.label))
    print(render_table(entries))


if __name__ == "__main__":
    main()
