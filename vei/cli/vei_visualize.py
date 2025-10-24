from __future__ import annotations

import html
import io
import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import typer
from rich import box
from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(add_completion=False)


@dataclass(slots=True)
class ReplayStep:
    index: int
    channel: str
    message: str


DEFAULT_CHANNEL_ORDER: Tuple[str, ...] = (
    "Plan",
    "Slack",
    "Mail",
    "Browser",
    "World",
    "Help",
    "Other",
)


FLOW_CHANNEL_LAYOUT: Tuple[dict[str, object], ...] = (
    {"id": "Plan", "label": "Plan", "x": 80, "y": 240, "color": "#7B5BFF"},
    {"id": "Slack", "label": "Slack", "x": 260, "y": 150, "color": "#36C5F0"},
    {"id": "Mail", "label": "Mail", "x": 260, "y": 330, "color": "#FFB347"},
    {"id": "Browser", "label": "Browser", "x": 420, "y": 90, "color": "#B57EDC"},
    {"id": "Docs", "label": "Docs", "x": 420, "y": 210, "color": "#66BB6A"},
    {"id": "Tickets", "label": "Tickets", "x": 420, "y": 330, "color": "#FF7043"},
    {"id": "CRM", "label": "CRM", "x": 580, "y": 150, "color": "#42A5F5"},
    {"id": "World", "label": "World", "x": 580, "y": 270, "color": "#8D6E63"},
    {"id": "Help", "label": "Help", "x": 740, "y": 150, "color": "#F06292"},
    {"id": "Misc", "label": "Misc", "x": 740, "y": 330, "color": "#9E9E9E"},
)

FLOW_CHANNEL_ORDER: Tuple[str, ...] = tuple(node["id"] for node in FLOW_CHANNEL_LAYOUT)
FLOW_CHANNEL_SET: set[str] = set(FLOW_CHANNEL_ORDER)


@dataclass
class FlowStep:
    index: int
    channel: str
    label: str
    tool: str | None
    prev_channel: str
    time_ms: int | None


@dataclass
class FlowDataset:
    key: str
    label: str
    steps: List[FlowStep]
    source: str
    question: str | None = None


def _load_transcript(path: Path) -> List[Dict[str, Any]]:
    if path.suffix == ".jsonl":
        entries: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entries.append(json.loads(line))
        return entries
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
        if isinstance(data, list):
            return data
        raise typer.BadParameter("Transcript JSON must be a list of entries.")


def _load_trace(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _discover_question(start: Path) -> str | None:
    """Attempt to extract the task question from a nearby summary file."""

    search_dirs = [start]
    for _ in range(4):
        parent = search_dirs[-1].parent
        if parent == search_dirs[-1]:
            break
        search_dirs.append(parent)

    for directory in search_dirs:
        summary = directory / "summary.txt"
        if summary.exists():
            try:
                with summary.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.lower().startswith("task:"):
                            return line.split(":", 1)[1].strip()
            except OSError:
                continue
    return None


FLOW_TOOL_PREFIX_MAP: Tuple[Tuple[str, str], ...] = (
    ("slack.", "Slack"),
    ("mail.", "Mail"),
    ("browser.", "Browser"),
    ("docs.", "Docs"),
    ("doc.", "Docs"),
    ("drive.", "Docs"),
    ("tickets.", "Tickets"),
    ("ticket.", "Tickets"),
    ("crm.", "CRM"),
    ("vei.", "World"),
    ("help.", "Help"),
    ("support.", "Tickets"),
)


def _flow_channel_from_tool(tool: str) -> str:
    tool = tool.lower()
    for prefix, channel in FLOW_TOOL_PREFIX_MAP:
        if tool.startswith(prefix):
            return channel
    return "Misc"


def _flow_channel_from_focus(focus: str | None) -> str:
    if not focus:
        return "Misc"
    focus = focus.lower()
    if focus in ("slack", "slack_thread"):
        return "Slack"
    if focus in ("mail", "inbox"):
        return "Mail"
    if focus in ("browser", "web"):
        return "Browser"
    if focus in ("docs", "doc", "drive"):
        return "Docs"
    if focus in ("tickets", "ticket"):
        return "Tickets"
    if focus in ("crm", "salesforce"):
        return "CRM"
    if focus in ("world", "router"):
        return "World"
    if focus == "help":
        return "Help"
    return "Misc"


def _flow_events_from_transcript_entry(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract flow events from a transcript entry."""

    events: List[Dict[str, Any]] = []
    meta = entry.get("meta")
    meta_time = meta.get("time_ms") if isinstance(meta, dict) else None

    if "llm_plan" in entry:
        plan = entry["llm_plan"]
        raw = None
        if isinstance(plan, dict):
            raw = plan.get("raw") or plan.get("parsed")
        elif isinstance(plan, str):
            raw = plan
        label = _shorten(str(raw) if raw else "Plan drafted", 72)
        events.append({"channel": "Plan", "label": label, "tool": "llm_plan", "time_ms": meta_time})
        return events

    if "plan_error" in entry:
        label = _shorten(str(entry["plan_error"]), 72)
        events.append({"channel": "Plan", "label": f"Plan error: {label}", "tool": "llm_plan_error", "time_ms": meta_time})
        return events

    if "tool_search" in entry:
        detail = entry["tool_search"]
        query = ""
        if isinstance(detail, dict):
            query = detail.get("query", "")
        label = f"Tool search: {_shorten(str(query), 64)}"
        events.append({"channel": "Plan", "label": label, "tool": "tool_search", "time_ms": meta_time})
        return events

    if "help" in entry:
        detail = entry["help"]
        label = _shorten(str(detail), 72)
        events.append({"channel": "Help", "label": label, "tool": "help", "time_ms": meta_time})
        return events

    if "action" in entry:
        action = entry["action"]
        if isinstance(action, dict):
            tool = str(action.get("tool", ""))
            channel = _flow_channel_from_tool(tool)
            label = _shorten(_format_action(tool, action), 90)
            events.append({"channel": channel, "label": label, "tool": tool, "time_ms": meta_time})
            return events

    if "observation" in entry:
        obs = entry["observation"]
        if isinstance(obs, dict):
            time_ms = obs.get("time_ms", meta_time)
            focus = obs.get("focus")
            channel = _flow_channel_from_focus(focus if isinstance(focus, str) else None)
            summary = obs.get("summary")
            if isinstance(summary, str) and summary.strip():
                label = _shorten(summary, 90)
            else:
                pending = obs.get("pending_events")
                if isinstance(pending, dict) and pending:
                    counts = ", ".join(f"{k}:{pending[k]}" for k in sorted(pending))
                    label = f"Pending events: {counts}"
                else:
                    label = "Observation"
            events.append({"channel": channel, "label": label, "tool": "vei.observe", "time_ms": time_ms})
            return events

    if "error" in entry:
        err = entry["error"]
        label = _shorten(str(err), 72)
        events.append({"channel": "Misc", "label": f"Error: {label}", "tool": "error", "time_ms": meta_time})
        return events

    # Fallback: treat as misc note
    label = _shorten(str(entry), 72)
    events.append({"channel": "Misc", "label": label, "tool": "unknown", "time_ms": meta_time})
    return events


TRACE_TARGET_CHANNEL_MAP: Dict[str, str] = {
    "slack": "Slack",
    "mail": "Mail",
    "browser": "Browser",
    "docs": "Docs",
    "doc": "Docs",
    "tickets": "Tickets",
    "ticket": "Tickets",
    "crm": "CRM",
    "world": "World",
    "help": "Help",
}


def _format_trace_event(record: Dict[str, Any]) -> str:
    target = record.get("target", "")
    payload = record.get("payload")
    if isinstance(payload, dict):
        text = payload.get("text") or payload.get("subj") or payload.get("summary")
        if text:
            return _shorten(str(text), 90)
    return f"Event: {target}"


def _flow_events_from_trace_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    time_ms = record.get("time_ms")

    if record.get("type") == "call":
        tool = str(record.get("tool", ""))
        channel = _flow_channel_from_tool(tool)
        action = {"tool": tool, "args": record.get("args", {})}
        label = _shorten(_format_action(tool, action), 90)
        events.append({"channel": channel, "label": label, "tool": tool, "time_ms": time_ms})
        return events

    if record.get("type") == "event":
        target = str(record.get("target", "")).lower()
        channel = TRACE_TARGET_CHANNEL_MAP.get(target)
        if channel:
            label = _flow_channel_from_focus(target) if target not in TRACE_TARGET_CHANNEL_MAP else _format_trace_event(record)
            events.append({"channel": channel, "label": label, "tool": f"{target}.event", "time_ms": time_ms})
            return events

    return events


def _flow_steps_from_trace(records: List[Dict[str, Any]]) -> List[FlowStep]:
    raw_events: List[Dict[str, Any]] = []
    for record in records:
        raw_events.extend(_flow_events_from_trace_record(record))
    return _build_flow_steps(raw_events)


def _build_flow_steps(raw_events: List[Dict[str, Any]]) -> List[FlowStep]:
    steps: List[FlowStep] = []
    prev_channel = "Plan"
    for idx, event in enumerate(raw_events):
        channel = event.get("channel") or "Misc"
        if channel not in FLOW_CHANNEL_SET:
            channel = "Misc"
        label = event.get("label")
        if not label:
            continue
        tool = event.get("tool")
        time_ms = event.get("time_ms")
        step = FlowStep(index=idx, channel=channel, label=str(label), tool=str(tool) if tool else None, prev_channel=prev_channel, time_ms=time_ms if isinstance(time_ms, int) else None)
        steps.append(step)
        prev_channel = channel
    return steps


def _flow_steps_from_transcript(entries: List[Dict[str, Any]]) -> List[FlowStep]:
    raw_events: List[Dict[str, Any]] = []
    for entry in entries:
        raw_events.extend(_flow_events_from_transcript_entry(entry))
    return _build_flow_steps(raw_events)


def _default_dataset_label(path: Path) -> str:
    """Create a friendly label from a transcript or trace path."""

    parent = path.parent.name if path.parent.name else path.name
    if parent:
        label = parent.replace("__", "/")
    else:
        label = path.stem.replace("__", "/")
    return label


def _dataset_key(label: str) -> str:
    text = label.lower().replace("/", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "dataset"


def _load_flow_dataset(source: Path, *, label: str | None = None) -> FlowDataset:
    effective_source = source
    steps: List[FlowStep] = []

    if not source.exists():
        raise typer.BadParameter(f"{source} does not exist")

    if source.is_dir():
        transcript = source / "transcript.json"
        trace = source / "trace.jsonl"
        if transcript.exists() and transcript.stat().st_size:
            entries = _load_transcript(transcript)
            steps = _flow_steps_from_transcript(entries)
            effective_source = transcript
        if not steps and trace.exists():
            records = _load_trace(trace)
            steps = _flow_steps_from_trace(records)
            effective_source = trace
    else:
        suffix = source.suffix.lower()
        if suffix == ".jsonl":
            records = _load_trace(source)
            steps = _flow_steps_from_trace(records)
        elif suffix == ".json":
            if source.stat().st_size:
                entries = _load_transcript(source)
                steps = _flow_steps_from_transcript(entries)
                effective_source = source
            if not steps:
                trace = source.parent / "trace.jsonl"
                if trace.exists():
                    records = _load_trace(trace)
                    steps = _flow_steps_from_trace(records)
                    effective_source = trace
        else:
            raise typer.BadParameter(f"Unsupported file type for visualization: {source}")

    if not steps:
        raise typer.BadParameter(f"No visualisable steps found for {source}")

    dataset_label = label or _default_dataset_label(effective_source)
    question = _discover_question(effective_source if effective_source.is_dir() else effective_source.parent)
    return FlowDataset(
        key=_dataset_key(dataset_label),
        label=dataset_label,
        steps=steps,
        source=str(effective_source),
        question=question,
    )


def _render_flow_html(
    datasets: List[FlowDataset],
    *,
    title: str,
    autoplay: bool,
    step_ms: int,
    question: str | None = None,
) -> str:
    environment_json = json.dumps(list(FLOW_CHANNEL_LAYOUT), ensure_ascii=False)
    dataset_payload: List[Dict[str, Any]] = []
    for ds in datasets:
        dataset_payload.append(
            {
                "key": ds.key,
                "label": ds.label,
                "source": ds.source,
                "steps": [
                    {
                        "index": step.index,
                        "channel": step.channel,
                        "label": step.label,
                        "tool": step.tool,
                        "prev": step.prev_channel,
                        "time_ms": step.time_ms,
                    }
                    for step in ds.steps
                ],
            }
        )
    datasets_json = json.dumps(dataset_payload, ensure_ascii=False)
    safe_title = html.escape(title)
    safe_question = html.escape(question) if question else ""
    autoplay_js = "true" if autoplay else "false"
    step_ms = max(50, step_ms)

    question_block = (
        f'<p class="question"><span>Scenario:</span> {safe_question}</p>' if safe_question else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #0f172a;
        --panel: rgba(15, 23, 42, 0.85);
        --panel-border: #1f2937;
        --text: #e2e8f0;
        --muted: #94a3b8;
        --accent: #38bdf8;
        --pulse: #f97316;
        font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}

      body {{
        margin: 0;
        min-height: 100vh;
        background: radial-gradient(circle at top left, rgba(56, 189, 248, 0.25), transparent 45%) var(--bg);
        color: var(--text);
        display: flex;
        justify-content: center;
        padding: 32px 24px 48px;
      }}

      .container {{
        max-width: 1100px;
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: 20px;
      }}

      header {{
        display: flex;
        flex-direction: column;
        gap: 8px;
      }}

      header h1 {{
        font-size: 28px;
        margin: 0;
      }}

      header p {{
        color: var(--muted);
        margin: 0;
      }}

      header p.question {{
        color: #fef3c7;
        font-size: 15px;
        background: rgba(234, 179, 8, 0.08);
        border: 1px solid rgba(250, 204, 21, 0.35);
        border-radius: 12px;
        padding: 10px 14px;
        display: inline-block;
      }}

      header p.question span {{
        color: #facc15;
        font-weight: 600;
        margin-right: 6px;
      }}

      .controls {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        align-items: center;
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 16px;
        padding: 12px 16px;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.35);
      }}

      .control {{
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: 13px;
        color: var(--muted);
      }}

      select,
      button {{
        background: rgba(15, 23, 42, 0.85);
        color: var(--text);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 14px;
        cursor: pointer;
        transition: border-color 0.2s ease, transform 0.1s ease;
      }}

      select:hover,
      button:hover {{
        border-color: var(--accent);
      }}

      button:active {{
        transform: translateY(1px);
      }}

      button[disabled],
      select[disabled] {{
        opacity: 0.5;
        cursor: default;
      }}

      .progress {{
        flex: 1;
        min-width: 140px;
        height: 6px;
        background: rgba(148, 163, 184, 0.2);
        border-radius: 999px;
        overflow: hidden;
      }}

      .progress-bar {{
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, rgba(56, 189, 248, 0.8), rgba(168, 85, 247, 0.8));
        transition: width 0.3s ease;
      }}

      .canvas-row {{
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
      }}

      svg {{
        flex: 1 1 640px;
        min-height: 420px;
        background: linear-gradient(160deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.92));
        border: 1px solid var(--panel-border);
        border-radius: 20px;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.45);
      }}

      .side-panel {{
        flex: 1 1 240px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }}

      .panel-card {{
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 18px;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        box-shadow: 0 16px 35px rgba(15, 23, 42, 0.35);
      }}

      .panel-card h2,
      .panel-card h3 {{
        margin: 0;
        font-size: 18px;
      }}

      .step-text {{
        font-size: 16px;
        line-height: 1.4;
        color: #f8fafc;
      }}

      .step-meta {{
        font-size: 13px;
        color: var(--muted);
        display: flex;
        flex-direction: column;
        gap: 2px;
      }}

      .panel-meta {{
        font-size: 12px;
        color: var(--muted);
      }}

      .dataset-label {{
        font-size: 15px;
        font-weight: 600;
        color: #f1f5f9;
      }}

      footer {{
        color: var(--muted);
        font-size: 12px;
        text-align: center;
        margin-top: 12px;
      }}

      .node {{
        transition: transform 0.3s ease;
      }}

      .node-circle {{
        fill: rgba(10, 18, 36, 0.95);
        stroke: rgba(148, 163, 184, 0.6);
        stroke-width: 2;
        filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.4));
      }}

      .node-halo {{
        fill: none;
        stroke: rgba(148, 163, 184, 0.4);
        stroke-width: 2;
        opacity: 0;
        transition: opacity 0.3s ease, stroke 0.3s ease;
      }}

      .node-label {{
        fill: #e2e8f0;
        font-size: 14px;
        text-anchor: middle;
        dominant-baseline: central;
      }}

      .node-sub {{
        fill: rgba(148, 163, 184, 0.7);
        font-size: 11px;
        text-anchor: middle;
      }}

      .node-visited .node-circle {{
        stroke: rgba(59, 130, 246, 0.7);
        stroke-width: 2.6;
      }}

      .node-active {{
        transform: translateY(-2px);
      }}

      .node-active .node-circle {{
        stroke-width: 3.4;
        stroke: #ffffff;
      }}

      .node-active .node-halo {{
        opacity: 1;
      }}

      .trail-edge {{
        stroke-width: 3;
        stroke-opacity: 0.25;
        stroke-linecap: round;
        filter: drop-shadow(0 0 6px rgba(255, 255, 255, 0.08));
      }}

      .pulse-edge {{
        stroke-width: 6;
        stroke-linecap: round;
        stroke-opacity: 0.88;
        filter: drop-shadow(0 0 10px rgba(255, 255, 255, 0.35));
        animation: pulseEdge 0.6s ease-out forwards;
      }}

      .node-pulse {{
        fill: none;
        stroke-width: 3;
        stroke-opacity: 0.7;
        animation: nodePulse 0.7s ease-out forwards;
      }}

      @keyframes pulseEdge {{
        0% {{
          stroke-opacity: 0.95;
          stroke-width: 8;
        }}
        100% {{
          stroke-opacity: 0.05;
          stroke-width: 2;
        }}
      }}

      @keyframes nodePulse {{
        0% {{
          stroke-opacity: 0.9;
          stroke-width: 5;
          r: 30;
        }}
        100% {{
          stroke-opacity: 0;
          stroke-width: 1;
          r: 46;
        }}
      }}

      @media (max-width: 900px) {{
        body {{
          padding: 20px 12px 32px;
        }}
        svg {{
          flex: 1 1 100%;
          min-height: 360px;
        }}
        .side-panel {{
          flex: 1 1 100%;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <header>
        <h1>{safe_title}</h1>
        {question_block if question_block else '<p>All runs share the same environment. Watch how each path lights up Slack, Mail, Docs, and more.</p>'}
        {'<p>All runs share the same environment. Watch how each path lights up Slack, Mail, Docs, and more.</p>' if question_block else ''}
      </header>
      <section class="controls">
        <label class="control">
          <span>Run</span>
          <select id="run-select"></select>
        </label>
        <button id="play-btn" type="button">Pause</button>
        <button id="step-btn" type="button">Step</button>
        <label class="control">
          <span>Speed</span>
          <select id="speed-select">
            <option value="200">Ultra (0.2s)</option>
            <option value="350">Fast (0.35s)</option>
            <option value="600" selected>Normal (0.6s)</option>
            <option value="900">Slow (0.9s)</option>
            <option value="1400">Leisure (1.4s)</option>
          </select>
        </label>
        <span id="step-counter">Step 0 / 0</span>
        <div class="progress">
          <div class="progress-bar" id="progress-bar"></div>
        </div>
      </section>
      <section class="canvas-row">
        <svg id="flow-canvas" viewBox="0 0 820 420">
          <rect x="0" y="0" width="820" height="420" fill="url(#bgGradient)"></rect>
          <defs>
            <linearGradient id="bgGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="rgba(15, 23, 42, 0.65)"></stop>
              <stop offset="50%" stop-color="rgba(2, 6, 23, 0.9)"></stop>
              <stop offset="100%" stop-color="rgba(9, 13, 24, 0.85)"></stop>
            </linearGradient>
          </defs>
          <g id="trail-group"></g>
          <g id="pulse-group"></g>
          <g id="node-group"></g>
        </svg>
        <aside class="side-panel">
          <div class="panel-card">
            <h2>Current Step</h2>
            <div id="step-label" class="step-text">Select a run to begin.</div>
            <div id="step-meta" class="step-meta">
              <span>Channel: —</span>
              <span>Tool: —</span>
              <span>Timestamp: —</span>
            </div>
          </div>
          <div class="panel-card">
            <h3>Dataset</h3>
            <div id="dataset-label" class="dataset-label">—</div>
            <div class="panel-meta">Source: <span id="source-label">—</span></div>
          </div>
        </aside>
      </section>
      <footer>
        Generated with <code>vei-visualize flow</code>. Same environment, different agent paths.
      </footer>
    </div>
    <script>
      const ENVIRONMENT = {environment_json};
      const DATASETS = {datasets_json};
      const CONFIG = {{ autoplay: {autoplay_js}, stepMs: {step_ms} }};

      const svgNS = "http://www.w3.org/2000/svg";
      const nodeGroup = document.getElementById("node-group");
      const trailGroup = document.getElementById("trail-group");
      const pulseGroup = document.getElementById("pulse-group");
      const runSelect = document.getElementById("run-select");
      const playBtn = document.getElementById("play-btn");
      const stepBtn = document.getElementById("step-btn");
      const speedSelect = document.getElementById("speed-select");
      const stepCounter = document.getElementById("step-counter");
      const progressBar = document.getElementById("progress-bar");
      const stepLabel = document.getElementById("step-label");
      const stepMeta = document.getElementById("step-meta");
      const datasetLabel = document.getElementById("dataset-label");
      const sourceLabel = document.getElementById("source-label");

      const nodeLookup = new Map();
      const visited = new Set();
      const state = {{ datasetIndex: 0, stepIndex: -1, playing: CONFIG.autoplay, timer: null, speed: CONFIG.stepMs }};

      function createNodeElements() {{
        nodeGroup.innerHTML = "";
        ENVIRONMENT.forEach((node) => {{
          const group = document.createElementNS(svgNS, "g");
          group.classList.add("node");
          group.dataset.channel = node.id;
          group.style.setProperty("--node-color", node.color);

          const halo = document.createElementNS(svgNS, "circle");
          halo.setAttribute("cx", node.x);
          halo.setAttribute("cy", node.y);
          halo.setAttribute("r", 32);
          halo.setAttribute("stroke", node.color);
          halo.classList.add("node-halo");

          const circle = document.createElementNS(svgNS, "circle");
          circle.setAttribute("cx", node.x);
          circle.setAttribute("cy", node.y);
          circle.setAttribute("r", 26);
          circle.setAttribute("stroke", node.color);
          circle.classList.add("node-circle");

          const label = document.createElementNS(svgNS, "text");
          label.setAttribute("x", node.x);
          label.setAttribute("y", node.y + 40);
          label.classList.add("node-label");
          label.textContent = node.label;

          group.appendChild(halo);
          group.appendChild(circle);
          group.appendChild(label);
          nodeGroup.appendChild(group);

          nodeLookup.set(node.id, {{ group, halo, circle, label, color: node.color, x: node.x, y: node.y }});
        }});
      }}

      function currentDataset() {{
        return DATASETS[state.datasetIndex] || null;
      }}

      function resetView() {{
        visited.clear();
        trailGroup.innerHTML = "";
        pulseGroup.innerHTML = "";
        nodeLookup.forEach((entry) => {{
          entry.group.classList.remove("node-active");
          entry.group.classList.remove("node-visited");
        }});
        stepLabel.textContent = "Ready.";
        stepMeta.innerHTML = "<span>Channel: —</span><span>Tool: —</span><span>Timestamp: —</span>";
        stepCounter.textContent = "Step 0 / 0";
        progressBar.style.width = "0%";
        state.stepIndex = -1;
      }}

      function updateDatasetInfo() {{
        const ds = currentDataset();
        if (!ds) {{
          datasetLabel.textContent = "No dataset";
          sourceLabel.textContent = "—";
          runSelect.disabled = true;
          playBtn.disabled = true;
          stepBtn.disabled = true;
          return;
        }}
        datasetLabel.textContent = ds.label;
        sourceLabel.textContent = ds.source;
        runSelect.disabled = DATASETS.length <= 1;
        playBtn.disabled = ds.steps.length === 0;
        stepBtn.disabled = ds.steps.length === 0;
      }}

      function highlightNode(channel) {{
        nodeLookup.forEach((entry, id) => {{
          if (channel && id === channel) {{
            entry.group.classList.add("node-active");
          }} else {{
            entry.group.classList.remove("node-active");
          }}
          if (visited.has(id)) {{
            entry.group.classList.add("node-visited");
          }} else {{
            entry.group.classList.remove("node-visited");
          }}
        }});
      }}

      function addNodePulse(node) {{
        pulseGroup.innerHTML = "";
        const pulse = document.createElementNS(svgNS, "circle");
        pulse.setAttribute("cx", node.x);
        pulse.setAttribute("cy", node.y);
        pulse.setAttribute("r", 32);
        pulse.setAttribute("stroke", node.color);
        pulse.classList.add("node-pulse");
        pulseGroup.appendChild(pulse);
        setTimeout(() => pulse.remove(), Math.min(state.speed + 200, 1200));
      }}

      function addEdge(prev, current) {{
        const prevNode = nodeLookup.get(prev);
        const currentNode = nodeLookup.get(current);
        if (!prevNode || !currentNode) {{
          return;
        }}
        if (prev === current) {{
          addNodePulse(currentNode);
          return;
        }}
        pulseGroup.innerHTML = "";

        const pulse = document.createElementNS(svgNS, "line");
        pulse.setAttribute("x1", prevNode.x);
        pulse.setAttribute("y1", prevNode.y);
        pulse.setAttribute("x2", currentNode.x);
        pulse.setAttribute("y2", currentNode.y);
        pulse.setAttribute("stroke", currentNode.color);
        pulse.classList.add("pulse-edge");
        pulseGroup.appendChild(pulse);

        const trail = document.createElementNS(svgNS, "line");
        trail.setAttribute("x1", prevNode.x);
        trail.setAttribute("y1", prevNode.y);
        trail.setAttribute("x2", currentNode.x);
        trail.setAttribute("y2", currentNode.y);
        trail.setAttribute("stroke", currentNode.color);
        trail.classList.add("trail-edge");
        trailGroup.appendChild(trail);

        if (trailGroup.childNodes.length > 600) {{
          trailGroup.removeChild(trailGroup.firstChild);
        }}
      }}

      function applyStep(step) {{
        visited.add(step.channel);
        highlightNode(step.channel);
        addEdge(step.prev, step.channel);

        stepLabel.textContent = step.label;
        const toolText = step.tool ? step.tool : "—";
        const timeText = typeof step.time_ms === "number" ? step.time_ms + " ms" : "—";
        stepMeta.innerHTML = `<span>Channel: ${{
          step.channel
        }}</span><span>Tool: ${{
          toolText
        }}</span><span>Timestamp: ${{
          timeText
        }}</span>`;
      }}

      function updateProgress() {{
        const ds = currentDataset();
        if (!ds || ds.steps.length === 0) {{
          stepCounter.textContent = "Step 0 / 0";
          progressBar.style.width = "0%";
          return;
        }}
        const total = ds.steps.length;
        const current = Math.max(0, state.stepIndex + 1);
        stepCounter.textContent = `Step ${{
          Math.min(current, total)
        }} / ${{
          total
        }}`;
        progressBar.style.width = `${{
          Math.min(100, (current / total) * 100)
        }}%`;
      }}

      function goToStep(index) {{
        const ds = currentDataset();
        if (!ds) {{
          return;
        }}
        if (index < -1) {{
          index = -1;
        }}
        if (index >= ds.steps.length) {{
          state.stepIndex = ds.steps.length - 1;
          updateProgress();
          state.playing = false;
          playBtn.textContent = "Replay";
          return;
        }}
        if (index === -1) {{
          resetView();
          updateProgress();
          return;
        }}
        // Step forward through intermediate steps to maintain trail.
        if (index < state.stepIndex) {{
          resetView();
          for (let i = 0; i <= index; i += 1) {{
            state.stepIndex = i;
            applyStep(ds.steps[i]);
          }}
        }} else {{
          for (let i = state.stepIndex + 1; i <= index; i += 1) {{
            state.stepIndex = i;
            applyStep(ds.steps[i]);
          }}
        }}
        updateProgress();
      }}

      function advance() {{
        const ds = currentDataset();
        if (!ds) {{
          return;
        }}
        const nextIndex = state.stepIndex + 1;
        if (nextIndex >= ds.steps.length) {{
          state.playing = false;
          playBtn.textContent = "Replay";
          return;
        }}
        goToStep(nextIndex);
      }}

      function scheduleNext() {{
        if (state.timer) {{
          clearTimeout(state.timer);
        }}
        if (!state.playing) {{
          return;
        }}
        state.timer = setTimeout(() => {{
          advance();
          if (state.playing) {{
            scheduleNext();
          }}
        }}, state.speed);
      }}

      function pause() {{
        state.playing = false;
        if (state.timer) {{
          clearTimeout(state.timer);
        }}
        playBtn.textContent = "Play";
      }}

      function play() {{
        const ds = currentDataset();
        if (!ds || ds.steps.length === 0) {{
          return;
        }}
        if (state.stepIndex >= ds.steps.length - 1) {{
          goToStep(-1);
        }}
        state.playing = true;
        playBtn.textContent = "Pause";
        scheduleNext();
      }}

      function togglePlay() {{
        if (state.playing) {{
          pause();
        }} else {{
          play();
        }}
      }}

      function changeDataset(index) {{
        pause();
        state.datasetIndex = index;
        state.stepIndex = -1;
        resetView();
        updateDatasetInfo();
        updateProgress();
        if (state.playing) {{
          play();
        }} else if (CONFIG.autoplay) {{
          play();
        }}
      }}

      function initControls() {{
        runSelect.innerHTML = "";
        DATASETS.forEach((ds, idx) => {{
          const option = document.createElement("option");
          option.value = String(idx);
          option.textContent = ds.label;
          runSelect.appendChild(option);
        }});
        if (DATASETS.length > 0) {{
          runSelect.value = "0";
        }}
        runSelect.addEventListener("change", (event) => {{
          const value = Number(event.target.value);
          changeDataset(value);
        }});
        playBtn.addEventListener("click", () => togglePlay());
        stepBtn.addEventListener("click", () => {{
          pause();
          advance();
        }});
        speedSelect.value = String(state.speed);
        speedSelect.addEventListener("change", (event) => {{
          const value = Number(event.target.value);
          state.speed = Math.max(80, value);
          if (state.playing) {{
            scheduleNext();
          }}
        }});
      }}

      function initialize() {{
        createNodeElements();
        initControls();
        updateDatasetInfo();
        resetView();
        updateProgress();
        if (CONFIG.autoplay && DATASETS.length > 0) {{
          play();
        }}
      }}

      initialize();
    </script>
  </body>
</html>
"""


def _shorten(text: str, max_len: int = 60) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _channel_for_tool(tool: str) -> str:
    if tool.startswith("slack."):
        return "Slack"
    if tool.startswith("mail."):
        return "Mail"
    if tool.startswith("browser."):
        return "Browser"
    if tool.startswith("vei.help") or tool.startswith("help."):
        return "Help"
    if tool.startswith("vei."):
        return "World"
    return "Other"


def _channel_for_focus(focus: str | None) -> str:
    if focus == "slack":
        return "Slack"
    if focus == "mail":
        return "Mail"
    if focus == "browser":
        return "Browser"
    if focus:
        return "World"
    return "World"


def _format_action(tool: str, action: Dict[str, Any]) -> str:
    args = action.get("args") or {}
    # Highlight the most relevant fields for common tools.
    if tool == "slack.send_message":
        text = args.get("text")
        if isinstance(text, str):
            return f"{tool} :: { _shorten(text, 55) }"
    if tool == "mail.compose":
        subj = args.get("subj") or args.get("subject")
        if isinstance(subj, str):
            return f"{tool} :: subj={ _shorten(subj, 50) }"
        to_addr = args.get("to")
        if isinstance(to_addr, str):
            return f"{tool} :: to={ _shorten(to_addr, 40) }"
    if tool.startswith("browser."):
        query = args.get("query")
        node_id = args.get("node_id")
        if isinstance(query, str):
            return f"{tool} :: query={ _shorten(query, 45) }"
        if isinstance(node_id, str):
            return f"{tool} :: target={ _shorten(node_id, 45) }"
    if tool.startswith("docs."):
        title = args.get("title") or args.get("name")
        if isinstance(title, str):
            return f"{tool} :: { _shorten(title, 55) }"
    if tool.startswith("tickets."):
        summary = args.get("summary") or args.get("title")
        if isinstance(summary, str):
            return f"{tool} :: { _shorten(summary, 55) }"
    if tool.startswith("crm."):
        name = args.get("company") or args.get("contact") or args.get("email") or args.get("id")
        if isinstance(name, str):
            return f"{tool} :: { _shorten(name, 55) }"
    if tool == "vei.tick":
        dt = args.get("dt_ms")
        if isinstance(dt, (int, float)):
            return f"{tool} :: dt_ms={int(dt)}"
    # Generic fallback: show up to two key=value pairs.
    parts: List[str] = []
    for idx, (key, value) in enumerate(args.items()):
        if idx >= 2:
            break
        parts.append(f"{key}={_shorten(str(value), 40)}")
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"{tool}{suffix}"


def _format_observation(obs: Dict[str, Any]) -> Tuple[str, str]:
    focus = obs.get("focus")
    channel = _channel_for_focus(focus if isinstance(focus, str) else None)
    summary = obs.get("summary")
    if isinstance(summary, str) and summary.strip():
        return channel, _shorten(summary, 60)
    pending = obs.get("pending_events")
    if isinstance(pending, dict) and pending:
        counts = ", ".join(f"{k}:{pending[k]}" for k in sorted(pending))
        return channel, f"pending events -> {counts}"
    return channel, "observation"


def _classify_entry(index: int, entry: Dict[str, Any]) -> Iterable[ReplayStep]:
    if "llm_plan" in entry:
        plan = entry["llm_plan"]
        raw = None
        if isinstance(plan, dict):
            raw = plan.get("raw") or plan.get("parsed")
        elif isinstance(plan, str):
            raw = plan
        text = _shorten(str(raw) if raw is not None else "plan", 60)
        yield ReplayStep(index=index, channel="Plan", message=text)
        return
    if "plan_error" in entry:
        detail = entry["plan_error"]
        yield ReplayStep(index=index, channel="Plan", message=_shorten(str(detail), 60))
        return
    if "help" in entry:
        help_data = entry["help"]
        yield ReplayStep(index=index, channel="Help", message=_shorten(str(help_data), 60))
        return
    if "action" in entry:
        action = entry["action"]
        if isinstance(action, dict):
            tool = str(action.get("tool") or "unknown")
            channel = _channel_for_tool(tool)
            yield ReplayStep(index=index, channel=channel, message=_format_action(tool, action))
            return
    if "observation" in entry:
        obs = entry["observation"]
        if isinstance(obs, dict):
            channel, message = _format_observation(obs)
            yield ReplayStep(index=index, channel=channel, message=message)
            return
    if "error" in entry:
        error = entry["error"]
        yield ReplayStep(index=index, channel="Other", message=_shorten(str(error), 60))
        return
    if "tool_search" in entry:
        search = entry["tool_search"]
        query = ""
        if isinstance(search, dict):
            query = search.get("query", "")
        yield ReplayStep(index=index, channel="Plan", message=f"tool search :: {_shorten(str(query), 50)}")
        return
    yield ReplayStep(index=index, channel="Other", message=_shorten(str(entry), 60))


def _gather_steps(entries: List[Dict[str, Any]]) -> List[ReplayStep]:
    steps: List[ReplayStep] = []
    for idx, entry in enumerate(entries):
        for step in _classify_entry(idx, entry):
            steps.append(step)
    return steps


def _build_panels(
    channel_history: Dict[str, List[ReplayStep]],
    current: ReplayStep | None,
    *,
    max_rows: int,
) -> Columns:
    panels: List[Panel] = []
    for channel in _determine_channel_order(channel_history):
        entries = channel_history.get(channel, [])
        rendered: List[str] = []
        for step in entries[-max_rows:]:
            prefix = "->" if current is not None and step is current else " -"
            rendered.append(f"{prefix} {step.message}")
        if not rendered:
            rendered.append(" idle")
        border_style = "bright_green" if current and current.channel == channel else "dim"
        panels.append(
            Panel(
                "\n".join(rendered),
                title=channel,
                border_style=border_style,
                box=box.ASCII,
            )
        )
    return Columns(panels, padding=1)


def _determine_channel_order(history: Dict[str, List[ReplayStep]]) -> List[str]:
    order: List[str] = list(DEFAULT_CHANNEL_ORDER)
    for channel in history:
        if channel not in order:
            order.append(channel)
    return order


def _render_frame(
    channel_history: Dict[str, List[ReplayStep]],
    current: ReplayStep | None,
    total_steps: int,
    *,
    max_rows: int,
) -> RenderableType:
    header_text = Text(
        f"Step {current.index + 1 if current else 0}/{total_steps}",
        style="bold white",
    )
    panels = _build_panels(channel_history, current, max_rows=max_rows)
    return Group(header_text, panels)


@app.command()
def replay(
    transcript: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, help="Transcript JSON/JSONL to replay"),
    delay: float = typer.Option(0.8, min=0.05, help="Seconds to wait between steps"),
    max_rows: int = typer.Option(6, min=3, max=12, help="Max lines to display per channel"),
) -> None:
    """Animate a transcript so the environment boxes light up as work completes."""

    entries = _load_transcript(transcript)
    steps = _gather_steps(entries)
    if not steps:
        raise typer.BadParameter("Transcript contained no recognisable steps to display.")

    console = Console()
    channel_history: Dict[str, List[ReplayStep]] = {ch: [] for ch in DEFAULT_CHANNEL_ORDER}

    try:
        with Live(console=console, refresh_per_second=8) as live:
            for step in steps:
                channel_history.setdefault(step.channel, []).append(step)
                live.update(_render_frame(channel_history, step, total_steps=len(steps), max_rows=max_rows))
                time.sleep(delay)
            # Show final state for a brief moment so the user can capture it.
            live.update(_render_frame(channel_history, steps[-1], total_steps=len(steps), max_rows=max_rows))
            time.sleep(delay)
    except KeyboardInterrupt:
        console.print(Text("Visualization interrupted.", style="dim"))


def _suggest_flow_output(source: Path, dataset: FlowDataset | None = None) -> Path:
    base_dir = source if source.is_dir() else source.parent
    name = dataset.key if dataset else _dataset_key(_default_dataset_label(source))
    return base_dir / f"{name}_flow.html"


@app.command()
def flow(
    source: Path = typer.Argument(..., exists=True, readable=True, help="Transcript JSON/JSONL, trace.jsonl, or run directory"),
    out: Path | None = typer.Option(None, help="HTML output path (defaults to <run>/flow.html)"),
    autoplay: bool = typer.Option(True, help="Start playing automatically"),
    step_ms: int = typer.Option(600, min=60, help="Delay between steps in milliseconds"),
    title: str | None = typer.Option(None, help="Page title override"),
    question: str | None = typer.Option(None, help="Scenario question override to surface in the header"),
) -> None:
    """Render a fixed-layout flow visualization as an interactive HTML page."""

    dataset = _load_flow_dataset(source)
    output_path = out or _suggest_flow_output(source, dataset)
    html_text = _render_flow_html(
        [dataset],
        title=title or f"Flow · {dataset.label}",
        autoplay=autoplay,
        step_ms=step_ms,
        question=question or dataset.question,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    typer.echo(f"Wrote flow visualization to {output_path}")


@app.command()
def dashboard(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True, help="Run directory containing per-model artifacts"),
    out: Path | None = typer.Option(None, help="HTML output path (defaults to <run>/flow_dashboard.html)"),
    autoplay: bool = typer.Option(True, help="Start playing automatically"),
    step_ms: int = typer.Option(600, min=60, help="Delay between steps in milliseconds"),
    title: str | None = typer.Option(None, help="Page title override"),
    question: str | None = typer.Option(None, help="Scenario question override for the shared layout"),
) -> None:
    """Bundle multiple runs into one HTML page with a run selector."""

    datasets: List[FlowDataset] = []
    for child in sorted(run_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        try:
            datasets.append(_load_flow_dataset(child))
        except typer.BadParameter:
            continue
    if not datasets:
        raise typer.BadParameter(f"No transcript/trace data found under {run_dir}")
    datasets.sort(key=lambda ds: ds.label.lower())
    output_path = out or (run_dir / "flow_dashboard.html")
    if question:
        question_text = question
    else:
        questions = {ds.question for ds in datasets if ds.question}
        question_text = questions.pop() if len(questions) == 1 else None

    html_text = _render_flow_html(
        datasets,
        title=title or f"Flow Dashboard · {run_dir.name}",
        autoplay=autoplay,
        step_ms=step_ms,
        question=question_text,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    typer.echo(f"Wrote flow dashboard to {output_path}")


@app.command()
def export(
    source: Path = typer.Argument(..., exists=True, readable=True, help="Transcript JSON/JSONL, trace.jsonl, or run directory"),
    out: Path = typer.Argument(..., writable=True, help="Output animated GIF path"),
    step_ms: int = typer.Option(600, min=60, help="Delay between steps in milliseconds"),
    question: str | None = typer.Option(None, help="Scenario question override"),
    width: int = typer.Option(1100, min=720, max=1400, help="Viewport width for capture"),
    height: int = typer.Option(720, min=480, max=1200, help="Viewport height for capture"),
    duration_ms: int = typer.Option(420, min=80, help="Frame duration in the output GIF"),
    stride: int = typer.Option(1, min=1, max=5, help="Capture every Nth step to shrink file size"),
) -> None:
    """Capture the flow visualization as an animated GIF (requires playwright + Pillow)."""

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise typer.BadParameter(
            "playwright is required for GIF export. Install extras via `pip install -e '.[browser]'`."
        ) from exc
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dependency
        raise typer.BadParameter(
            "Pillow is required for GIF export. Install via `pip install Pillow`."
        ) from exc

    dataset = _load_flow_dataset(source)
    html_text = _render_flow_html(
        [dataset],
        title=f"Flow · {dataset.label}",
        autoplay=False,
        step_ms=step_ms,
        question=question or dataset.question,
    )

    if out.suffix.lower() != ".gif":
        raise typer.BadParameter("Only .gif export is currently supported.")
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vei_flow_") as tmp_dir:
        html_path = Path(tmp_dir) / "flow.html"
        html_path.write_text(html_text, encoding="utf-8")

        frames: List[Image.Image] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(html_path.as_uri(), wait_until="networkidle")
            # Ensure deterministic starting state
            page.evaluate("pause(); resetView(); updateDatasetInfo(); updateProgress();")
            page.wait_for_timeout(200)

            total_steps = len(dataset.steps)
            if total_steps == 0:
                raise typer.BadParameter(f"No steps available to export for {source}")

            step_stride = max(1, stride)
            captured_indices: set[int] = set()
            for idx in range(0, total_steps, step_stride):
                page.evaluate(f"goToStep({idx});")
                page.wait_for_timeout(step_ms / 2)
                buffer = page.screenshot(full_page=True)
                frames.append(Image.open(io.BytesIO(buffer)).convert("RGB"))
                captured_indices.add(idx)

            if (total_steps - 1) not in captured_indices:
                page.evaluate(f"goToStep({total_steps - 1});")
                page.wait_for_timeout(step_ms / 2)
                buffer = page.screenshot(full_page=True)
                frames.append(Image.open(io.BytesIO(buffer)).convert("RGB"))

            browser.close()

        if not frames:
            raise typer.BadParameter("Failed to capture any frames for GIF export.")

        first, *rest = frames
        first.save(
            out,
            save_all=True,
            append_images=rest,
            duration=duration_ms,
            loop=0,
            optimize=True,
        )
    typer.echo(f"Wrote flow animation to {out}")


if __name__ == "__main__":
    app()
