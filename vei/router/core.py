from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
import heapq
import threading
import queue
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from vei.world.scenario import Scenario
from vei.world.scenarios import load_from_env
from vei.monitors.manager import MonitorManager
from vei.monitors.models import MonitorFinding
from vei.policy import DEFAULT_RULES, PolicyEngine, PromoteMonitorRule
from vei.world.drift import DriftEngine
from vei.world.state import Event as StateEvent, StateStore
from .tool_registry import ToolRegistry, ToolSpec


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


class MCPError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class Observation(BaseModel):
    time_ms: int
    focus: str
    summary: str
    screenshot_ref: Optional[str] = None
    action_menu: List[Dict[str, Any]]
    pending_events: Dict[str, int]


@dataclass
class Event:
    t_due_ms: int
    target: str
    payload: Dict[str, Any]


class LinearCongruentialGenerator:
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def next_u32(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def next_float(self) -> float:
        return self.next_u32() / 0x100000000

    def randint(self, a: int, b: int) -> int:
        return a + int(self.next_float() * (b - a + 1))


class EventBus:
    def __init__(self, seed: int):
        self.rng = LinearCongruentialGenerator(seed)
        self.clock_ms = 0
        self._heap: list[tuple[int, int, Event]] = []
        self._seq = 0

    def schedule(self, dt_ms: int, target: str, payload: Dict[str, Any]) -> None:
        evt = Event(self.clock_ms + dt_ms, target, payload)
        self._seq += 1
        heapq.heappush(self._heap, (evt.t_due_ms, self._seq, evt))

    def next_if_due(self) -> Optional[Event]:
        if self._heap and self._heap[0][0] <= self.clock_ms:
            _, _, evt = heapq.heappop(self._heap)
            return evt
        return None

    def advance(self, dt_ms: int) -> None:
        self.clock_ms += dt_ms

    def peek_due_time(self) -> Optional[int]:
        return self._heap[0][0] if self._heap else None

    def pending_count(self, target: Optional[str] = None) -> int:
        if target is None:
            return len(self._heap)
        return sum(1 for _, _, e in self._heap if e.target == target)


class TraceLogger:
    def __init__(self, out_dir: Optional[str]):
        self.out_dir = out_dir
        self.entries: List[Dict[str, Any]] = []
        # Optional: stream each entry to an external collector
        self.post_url: Optional[str] = os.environ.get("VEI_TRACE_POST_URL")
        self._flush_idx = 0
        self.append_mode = os.environ.get("VEI_TRACE_APPEND", "1") == "1"
        # Background poster for streaming to avoid inline latency
        self._q: queue.Queue[Dict[str, Any]] | None = None
        self._poster_thread: threading.Thread | None = None
        if self.post_url:
            self._q = queue.Queue(maxsize=256)
            self._poster_thread = threading.Thread(target=self._poster_loop, name="vei-trace-poster", daemon=True)
            self._poster_thread.start()

    def _try_stream(self, entry: Dict[str, Any]) -> None:
        if not self._q:
            return
        try:
            self._q.put_nowait(entry)
        except queue.Full:
            # Drop when saturated to preserve determinism and low latency
            pass

    def _poster_loop(self) -> None:
        # Use stdlib to avoid extra deps
        import urllib.request
        while True:
            try:
                item = self._q.get(timeout=1.0) if self._q else None
            except queue.Empty:
                continue
            if not item:
                continue
            try:
                data = json.dumps(item).encode("utf-8")
                req = urllib.request.Request(
                    self.post_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=1.0) as _:
                    pass
            except Exception:
                # Best-effort only
                pass

    def record_call(self, tool: str, args: Dict[str, Any], response: Any, time_ms: int) -> None:
        entry = {
            "trace_version": 1,
            "type": "call",
            "tool": tool,
            "args": args,
            "response": response,
            "time_ms": time_ms,
        }
        self.entries.append(entry)
        self._try_stream(entry)

    def record_event(self, target: str, payload: Dict[str, Any], emitted: Any, time_ms: int) -> None:
        entry = {
            "trace_version": 1,
            "type": "event",
            "target": target,
            "payload": payload,
            "emitted": emitted,
            "time_ms": time_ms,
        }
        self.entries.append(entry)
        self._try_stream(entry)

    def flush(self) -> None:
        # Allow late-binding of artifacts dir via environment during tests
        if not self.out_dir:
            env_dir = os.environ.get("VEI_ARTIFACTS_DIR")
            if env_dir:
                self.out_dir = env_dir
            else:
                return
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, "trace.jsonl")
        if self.append_mode and os.path.exists(path):
            mode = "a"
        else:
            mode = "w"
            self._flush_idx = 0
        with open(path, mode, encoding="utf-8") as f:
            for entry in self.entries[self._flush_idx : ]:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._flush_idx = len(self.entries)


def _reduce_router_init(state: Dict[str, Any], event: StateEvent) -> None:
    meta = state.setdefault("meta", {})
    meta.update(
        {
            "seed": event.payload.get("seed"),
            "scenario": event.payload.get("scenario"),
            "branch": event.payload.get("branch"),
        }
    )


def _reduce_tool_call(state: Dict[str, Any], event: StateEvent) -> None:
    calls = state.setdefault("tool_calls", [])
    calls.append(
        {
            "index": event.index,
            "tool": event.payload.get("tool"),
            "time_ms": event.payload.get("time_ms"),
        }
    )
    if len(calls) > 200:
        del calls[: len(calls) - 200]


def _reduce_event_delivery(state: Dict[str, Any], event: StateEvent) -> None:
    deliveries = state.setdefault("deliveries", {})
    target = str(event.payload.get("target"))
    deliveries[target] = deliveries.get(target, 0) + 1


def _reduce_drift_schedule(state: Dict[str, Any], event: StateEvent) -> None:
    drift_state = state.setdefault("drift", {})
    scheduled = drift_state.setdefault("scheduled", [])
    scheduled.append(
        {
            "job": event.payload.get("job"),
            "target": event.payload.get("target"),
            "dt_ms": event.payload.get("dt_ms"),
        }
    )
    if len(scheduled) > 100:
        del scheduled[: len(scheduled) - 100]


def _reduce_drift_delivered(state: Dict[str, Any], event: StateEvent) -> None:
    drift_state = state.setdefault("drift", {})
    delivered = drift_state.setdefault("delivered", {})
    job = event.payload.get("job")
    if job is None:
        return
    delivered[job] = delivered.get(job, 0) + 1


def _reduce_monitor_finding(state: Dict[str, Any], event: StateEvent) -> None:
    monitor_state = state.setdefault("monitors", {})
    findings = monitor_state.setdefault("findings", [])
    findings.append(event.payload)
    if len(findings) > 100:
        del findings[: len(findings) - 100]


def _reduce_policy_finding(state: Dict[str, Any], event: StateEvent) -> None:
    policy_state = state.setdefault("policy", {})
    findings = policy_state.setdefault("findings", [])
    findings.append(event.payload)
    if len(findings) > 200:
        del findings[: len(findings) - 200]


class SlackSim:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        # Configurable behavior
        if scenario and scenario.budget_cap_usd is not None:
            self.budget_cap_usd = int(scenario.budget_cap_usd)
        else:
            self.budget_cap_usd = int(os.environ.get("VEI_BUDGET_CAP", "3500"))
        try:
            if scenario and scenario.derail_prob is not None:
                self.derail_prob = float(scenario.derail_prob)
            else:
                self.derail_prob = float(os.environ.get("VEI_SLACK_DERAIL_PCT", "0.1"))
        except ValueError:
            self.derail_prob = 0.1

        initial_text = (
            scenario.slack_initial_message
            if scenario and scenario.slack_initial_message is not None
            else "Reminder: citations required for any request over $2k."
        )

        self.channels = {
            "#procurement": {
                "messages": [
                    {
                        "ts": "1",
                        "user": "itops",
                        "text": initial_text,
                        "thread_ts": None,
                    }
                ],
                "unread": 0,
            }
        }

    # MCP tools
    def list_channels(self) -> List[str]:
        return list(self.channels.keys())

    def open_channel(self, channel: str) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        return {"messages": ch["messages"], "unread_count": ch["unread"]}

    def send_message(self, channel: str, text: str, thread_ts: Optional[str] = None) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        # Monotonic 1-based timestamps to avoid duplicate ids
        ts = str(len(ch["messages"]) + 1)
        msg = {"ts": ts, "user": "agent", "text": text, "thread_ts": thread_ts}
        ch["messages"].append(msg)
        lower = text.lower()
        # Occasionally derail/off-topic before anything else
        if self.bus.rng.next_float() < self.derail_prob:
            self.bus.schedule(
                dt_ms=7000,
                target="slack",
                payload={
                    "channel": channel,
                    "text": "Could someone update the Q3 KPI sheet?",
                    "thread_ts": ts,
                },
            )
        # Approval policy: must include a budget number and be <= budget cap
        if ("approve" in lower or "summary" in lower or "budget" in lower):
            m = re.search(r"\$?([0-9]{3,6})", text.replace(",", ""))
            if m:
                amount = int(m.group(1))
                if amount <= self.budget_cap_usd:
                    self.bus.schedule(
                        dt_ms=12000,
                        target="slack",
                        payload={
                            "channel": channel,
                            "text": ":white_check_mark: Approved",
                            "thread_ts": ts,
                        },
                    )
                else:
                    self.bus.schedule(
                        dt_ms=10000,
                        target="slack",
                        payload={
                            "channel": channel,
                            "text": "Need clearer budget justification (over cap).",
                            "thread_ts": ts,
                        },
                    )
            else:
                self.bus.schedule(
                    dt_ms=9000,
                    target="slack",
                    payload={
                        "channel": channel,
                        "text": "What is the budget amount?",
                        "thread_ts": ts,
                    },
                )
        return {"ts": ts}

    def react(self, channel: str, ts: str, emoji: str) -> Dict[str, Any]:
        return {"ok": True}

    def fetch_thread(self, channel: str, thread_ts: str) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        base = _safe_int(thread_ts, 0)
        msgs = [
            m
            for m in ch["messages"]
            if m.get("thread_ts") in (thread_ts, None) and _safe_int(m.get("ts"), 0) >= base
        ]
        return {"messages": msgs}

    # Event delivery
    def deliver(self, event: Dict[str, Any]) -> Dict[str, Any]:
        channel = event["channel"]
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel")
        ts = str(len(ch["messages"]) + 1)
        ch["messages"].append({"ts": ts, "user": "cfo", "text": event["text"], "thread_ts": event.get("thread_ts")})
        ch["unread"] += 1
        return {"ok": True}


class MailSim:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.inbox: List[str] = []
        self.counter = 1
        self._variants_override = scenario.vendor_reply_variants if scenario and scenario.vendor_reply_variants else None

    def list(self, folder: str = "INBOX") -> List[Dict[str, Any]]:
        return [self.messages[mid] for mid in self.inbox]

    def open(self, id: str) -> Dict[str, Any]:
        m = self.messages.get(id)
        if not m:
            raise MCPError("unknown_message", f"Unknown mail id: {id}")
        return {"headers": m["headers"], "body_text": m["body_text"], "parts": m.get("parts", [])}

    def compose(self, to: str, subj: str, body_text: str, attachments: Optional[List[str]] = None) -> Dict[str, Any]:
        mid = f"m{self.counter}"
        self.counter += 1
        self.messages[mid] = {
            "id": mid,
            "from": "me@example",
            "to": to,
            "subj": subj,
            "time": self.bus.clock_ms,
            "unread": False,
            "headers": {"From": "me@example", "To": to, "Subject": subj},
            "body_text": body_text,
        }
        # Schedule vendor reply with varied templates (scenario override if provided)
        variants = self._variants_override or [
            "Thanks — Price: $3199, ETA: 5-7 business days.",
            "> On Mon, we received your request\nPRICE: USD 3,199\nEta: within 5-7 business days\n--\nBest, MacroCompute",
            "quote attached (inline): total: $3,199.00, ETA: 5 business days. Regards, Sales",
            "PRICE - $3199; eta: approx. 1 week\n\n\nJohn Doe\nSales Representative\nMacroCompute",
        ]
        idx = 0 if not variants else self.bus.rng.randint(0, max(0, len(variants) - 1))
        body = variants[idx] if variants else ""

        self.bus.schedule(
            dt_ms=15000,
            target="mail",
            payload={
                "in_reply_to": mid,
                "from": to,
                "subj": f"Re: {subj}",
                "body_text": body,
            },
        )
        return {"id": mid}

    def reply(self, id: str, body_text: str) -> Dict[str, Any]:
        return self.compose(to=self.messages[id]["from"], subj=f"Re: {self.messages[id]['subj']}", body_text=body_text)

    def deliver(self, event: Dict[str, Any]) -> Dict[str, Any]:
        mid = f"m{self.counter}"
        self.counter += 1
        msg = {
            "id": mid,
            "from": event["from"],
            "to": "me@example",
            "subj": event["subj"],
            "time": self.bus.clock_ms,
            "unread": True,
            "headers": {"From": event["from"], "To": "me@example", "Subject": event["subj"]},
            "body_text": event["body_text"],
        }
        self.messages[mid] = msg
        self.inbox.insert(0, mid)
        return {"id": mid}


class BrowserVirtual:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        # Very small virtual site with two pages and one affordance
        default_nodes = {
            "home": {
                "url": "https://vweb.local/home",
                "title": "MacroCompute — Home",
                "excerpt": "Welcome to MacroCompute. Find laptops and specs.",
                "affordances": [
                    {"tool": "browser.click", "args": {"node_id": "CLICK:open_pdp#0"}, "name": "Open product page"},
                ],
                "next": {"CLICK:open_pdp#0": "pdp"},
            },
            "pdp": {
                "url": "https://vweb.local/pdp/macrobook-pro-16",
                "title": "MacroBook Pro 16 — Product",
                "excerpt": "Powerful 16-inch laptop. Price $3199. See specifications.",
                "affordances": [
                    {"tool": "browser.click", "args": {"node_id": "CLICK:open_specs#0"}, "name": "See specifications"},
                    {"tool": "browser.back", "args": {}, "name": "Back to home"},
                ],
                "next": {"CLICK:open_specs#0": "specs", "BACK": "home"},
            },
            "specs": {
                "url": "https://vweb.local/pdp/macrobook-pro-16/specs",
                "title": "MacroBook Pro 16 — Specifications",
                "excerpt": "16-core CPU, 32GB RAM, 1TB SSD",
                "affordances": [
                    {"tool": "browser.back", "args": {}, "name": "Back to product"},
                ],
                "next": {"BACK": "pdp"},
            },
        }
        self.nodes = scenario.browser_nodes if scenario and scenario.browser_nodes else default_nodes
        self.state = "home"

    def open(self, url: str) -> Dict[str, Any]:
        if "pdp" in url:
            self.state = "pdp"
        else:
            self.state = "home"
        return {"url": self.nodes[self.state]["url"], "title": self.nodes[self.state]["title"]}

    def find(self, query: str, top_k: int = 10) -> Dict[str, Any]:
        node = self.nodes[self.state]
        hits = []
        for a in node["affordances"]:
            name = a.get("name") or a["args"].get("node_id", "")
            # Only include affordances that have a concrete click target
            args = a.get("args", {})
            node_id = args.get("node_id")
            if node_id is None:
                # Skip generic affordances like browser.back that lack node_id
                continue
            hits.append({
                "node_id": node_id,
                "role": a.get("role", "button"),
                "name": name,
            })
        return {"hits": hits[:top_k]}

    def click(self, node_id: str) -> Dict[str, Any]:
        node = self.nodes[self.state]
        nxt = node["next"].get(node_id)
        if not nxt:
            raise MCPError("invalid_action", f"Invalid click target: {node_id}")
        self.state = nxt
        return {"url": self.nodes[self.state]["url"]}

    def type(self, node_id: str, text: str) -> Dict[str, Any]:
        return {"ok": True}

    def submit(self, form_id: str) -> Dict[str, Any]:
        return {"url": self.nodes[self.state]["url"]}

    def read(self) -> Dict[str, Any]:
        node = self.nodes[self.state]
        return {
            "url": node["url"],
            "title": node["title"],
            "excerpt": node["excerpt"],
        }

    def back(self) -> Dict[str, Any]:
        node = self.nodes[self.state]
        nxt = node["next"].get("BACK")
        if not nxt:
            return {"url": node["url"]}
        self.state = nxt
        return {"url": self.nodes[self.state]["url"]}


class Router:
    def __init__(self, seed: int, artifacts_dir: Optional[str] = None, scenario: Optional[Scenario] = None):
        self.bus = EventBus(seed)

        state_dir_env = os.environ.get("VEI_STATE_DIR")
        base_dir = Path(state_dir_env).expanduser() if state_dir_env else None
        self.state_store = StateStore(base_dir=base_dir)
        self.state_store.register_reducer("router.init", _reduce_router_init)
        self.state_store.register_reducer("tool.call", _reduce_tool_call)
        self.state_store.register_reducer("event.delivery", _reduce_event_delivery)
        self.state_store.register_reducer("drift.schedule", _reduce_drift_schedule)
        self.state_store.register_reducer("drift.delivered", _reduce_drift_delivered)
        self.state_store.register_reducer("monitor.finding", _reduce_monitor_finding)
        self.state_store.register_reducer("policy.finding", _reduce_policy_finding)
        self._snapshot_interval = 25 if base_dir else None
        self._receipts: List[Dict[str, Any]] = []
        self._receipts_path: Optional[Path] = None
        if self.state_store.storage_dir:
            self._receipts_path = self.state_store.storage_dir / "receipts.jsonl"
            self._load_receipts()

        self.registry = ToolRegistry()
        self._seed_tool_registry()
        monitors_env = os.environ.get("VEI_MONITORS", "").strip()
        monitor_names = [m.strip() for m in (monitors_env.split(",") if monitors_env else []) if m.strip()]
        self.monitor_manager = MonitorManager(self.registry, monitor_names)
        rules = list(DEFAULT_RULES)
        policy_promote_env = os.environ.get("VEI_POLICY_PROMOTE", "").strip()
        if policy_promote_env:
            for item in policy_promote_env.split(","):
                token = item.strip()
                if not token:
                    continue
                if ":" in token:
                    code, severity = token.split(":", 1)
                    rules.append(PromoteMonitorRule(code.strip(), severity=severity.strip() or "warning"))
                else:
                    rules.append(PromoteMonitorRule(token, severity="warning"))
        self.policy_engine = PolicyEngine(rules)
        self._policy_findings: List[Dict[str, Any]] = []

        self.trace = TraceLogger(artifacts_dir)
        self.scenario = scenario or load_from_env(seed)
        self.slack = SlackSim(self.bus, self.scenario)
        self.mail = MailSim(self.bus, self.scenario)
        self.browser = BrowserVirtual(self.bus, self.scenario)
        for evt in self.scenario.derail_events or []:
            try:
                dt = int(evt.get("dt_ms", 0))
                target = evt.get("target")
                payload = evt.get("payload", {})
                if target:
                    self.bus.schedule(dt_ms=dt, target=target, payload=payload)
            except Exception:
                continue
        # Optional ERP twin
        try:
            from .erp import ErpSim  # local import to avoid import-time failures
            self.erp = ErpSim(self.bus, self.scenario)
        except Exception:
            self.erp = None  # type: ignore[attr-defined]
        # Optional CRM twin
        try:
            from .crm import CrmSim
            self.crm = CrmSim(self.bus, self.scenario)
        except Exception:
            self.crm = None  # type: ignore[attr-defined]

        drift_seed_env = os.environ.get("VEI_DRIFT_SEED")
        try:
            drift_seed = int(drift_seed_env) if drift_seed_env is not None else (seed ^ 0xD1F7)
        except ValueError:
            drift_seed = seed ^ 0xD1F7
        drift_mode = os.environ.get("VEI_DRIFT_MODE") or os.environ.get("VEI_DRIFT_RATE") or "off"
        self.drift = DriftEngine(state_store=self.state_store, bus=self.bus, seed=drift_seed, mode=drift_mode)
        self.drift.prime()

        existing_policy = self.state_store.materialised_state().get("policy", {})
        if isinstance(existing_policy, dict):
            findings = existing_policy.get("findings", [])
            if isinstance(findings, list):
                self._policy_findings.extend(findings)

        self._record_router_init(seed)

    @staticmethod
    def _jsonable(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except TypeError:
            if isinstance(value, dict):
                return {k: Router._jsonable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [Router._jsonable(v) for v in value]
            if isinstance(value, tuple):
                return [Router._jsonable(v) for v in value]
            if isinstance(value, set):
                return [Router._jsonable(v) for v in sorted(value)]
            return repr(value)

    def _append_state(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        clock_ms: Optional[int] = None,
    ) -> Optional[StateEvent]:
        payload_map = {k: Router._jsonable(v) for k, v in dict(payload or {}).items()}
        event = self.state_store.append(kind, payload_map, clock_ms=clock_ms or self.bus.clock_ms)
        if self._snapshot_interval and event.index % self._snapshot_interval == 0:
            self.state_store.take_snapshot()
        return event

    def _record_router_init(self, seed: int) -> None:
        scenario_name = getattr(self.scenario, "name", None)
        payload = {"seed": seed, "scenario": scenario_name, "branch": self.state_store.branch}
        self._append_state("router.init", payload)
        if self._snapshot_interval:
            self.state_store.take_snapshot()

    def _record_tool_call(self, tool: str, args: Dict[str, Any], result: Any) -> None:
        payload = {
            "tool": tool,
            "args": {k: Router._jsonable(v) for k, v in dict(args or {}).items()},
            "time_ms": self.bus.clock_ms,
        }
        event = self._append_state("tool.call", payload)
        receipt = {
            "tool": tool,
            "time_ms": self.bus.clock_ms,
            "state_head": self.state_store.head,
            "event_index": event.index if event else None,
        }
        try:
            receipt["result_preview"] = Router._jsonable(result)
        except Exception:
            receipt["result_preview"] = repr(result)
        self._receipts.append(receipt)
        if len(self._receipts) > 50:
            self._receipts.pop(0)
        self._write_receipt(receipt)

        findings: List[Any] = []
        if self.monitor_manager.monitors():
            snapshot = self.state_snapshot(include_state=False, tool_tail=0, include_receipts=False)
            findings = self.monitor_manager.after_tool_call(
                tool=tool,
                args=args,
                result=result,
                snapshot=snapshot,
            )
            for finding in findings:
                payload = {
                    "monitor": finding.monitor,
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity,
                    "time_ms": finding.time_ms,
                    "tool": finding.tool,
                    "metadata": Router._jsonable(finding.metadata),
                }
                self._append_state("monitor.finding", payload)
        if findings:
            policy_findings = self.policy_engine.evaluate(findings)
            for pf in policy_findings:
                payload = {
                    "code": pf.code,
                    "message": pf.message,
                    "severity": pf.severity,
                    "time_ms": pf.time_ms,
                    "tool": pf.tool,
                    "metadata": Router._jsonable(pf.metadata),
                }
                self._policy_findings.append(payload)
                self._append_state("policy.finding", payload)
        if len(self._policy_findings) > 200:
            self._policy_findings = self._policy_findings[-200:]

    def _record_event_delivery(self, target: str, payload: Dict[str, Any]) -> None:
        st_payload = {
            "target": target,
            "payload": Router._jsonable(payload),
            "time_ms": self.bus.clock_ms,
        }
        self._append_state("event.delivery", st_payload)
        if getattr(self, "drift", None) is not None:
            try:
                self.drift.handle_delivery(target, payload)
            except Exception:
                # Drift is best-effort; never break the main loop.
                pass

    def _load_receipts(self) -> None:
        if not self._receipts_path or not self._receipts_path.exists():
            return
        try:
            with self._receipts_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self._receipts.append(data)
        except Exception:
            self._receipts = []

    def _write_receipt(self, receipt: Dict[str, Any]) -> None:
        if not self._receipts_path:
            return
        try:
            with self._receipts_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(receipt, sort_keys=True) + "\n")
        except Exception:
            pass

    def state_snapshot(
        self,
        *,
        include_state: bool = False,
        tool_tail: int = 20,
        include_receipts: bool = True,
    ) -> Dict[str, Any]:
        state = self.state_store.materialised_state()
        tool_calls: List[Dict[str, Any]] = list(state.get("tool_calls", []))
        tail = tool_calls[-tool_tail:] if tool_tail and tool_tail > 0 else tool_calls
        deliveries = dict(state.get("deliveries", {}))
        drift_state = state.get("drift", {})
        drift_summary = {
            "scheduled_count": len(drift_state.get("scheduled", [])),
            "delivered": dict(drift_state.get("delivered", {})),
        }
        snapshot: Dict[str, Any] = {
            "head": self.state_store.head,
            "branch": self.state_store.branch,
            "time_ms": self.bus.clock_ms,
            "meta": dict(state.get("meta", {})),
            "tool_tail": tail,
            "deliveries": deliveries,
            "drift": drift_summary,
        }
        monitor_tail = [asdict(f) for f in self.monitor_manager.findings_tail(tool_tail or 20)]
        snapshot["monitor_findings"] = monitor_tail
        policy_tail: List[Dict[str, Any]] = []
        for item in self._policy_findings[-(tool_tail or 20):]:
            policy_tail.append(
                {
                    "code": item.get("code"),
                    "message": item.get("message"),
                    "severity": item.get("severity"),
                    "time_ms": item.get("time_ms"),
                    "tool": item.get("tool"),
                    "metadata": item.get("metadata", {}),
                }
            )
        snapshot["policy_findings"] = policy_tail
        if include_receipts:
            snapshot["receipts"] = list(self._receipts[-tool_tail:]) if tool_tail else list(self._receipts)
        if include_state:
            snapshot["state"] = state
        return snapshot

    def _seed_tool_registry(self) -> None:
        specs = [
            ToolSpec(
                name="vei.observe",
                description="Obtain the current observation (advances time).",
                side_effects=("time_advance",),
                default_latency_ms=1000,
            ),
            ToolSpec(
                name="vei.tick",
                description="Advance logical time and deliver due events.",
                side_effects=("time_advance", "event_delivery"),
            ),
            ToolSpec(
                name="vei.act_and_observe",
                description="Execute a tool then fetch the next observation.",
                side_effects=("time_advance",),
            ),
            ToolSpec(
                name="vei.state",
                description="Inspect state head, receipts, and recent tool calls.",
                side_effects=(),
            ),
            ToolSpec(
                name="slack.send_message",
                description="Post a message into a Slack channel thread.",
                side_effects=("slack_outbound",),
                permissions=("slack:write",),
                default_latency_ms=500,
            ),
            ToolSpec(
                name="slack.open_channel",
                description="Open a Slack channel view.",
                side_effects=(),
                permissions=("slack:read",),
            ),
            ToolSpec(
                name="slack.fetch_thread",
                description="Fetch a Slack thread for review.",
                side_effects=(),
                permissions=("slack:read",),
            ),
            ToolSpec(
                name="slack.list_channels",
                description="List available Slack channels.",
                permissions=("slack:read",),
            ),
            ToolSpec(
                name="slack.react",
                description="Add a reaction to a Slack message.",
                side_effects=("slack_outbound",),
                permissions=("slack:write",),
            ),
            ToolSpec(
                name="mail.compose",
                description="Send an email to a recipient.",
                side_effects=("mail_outbound", "event_schedule"),
                permissions=("mail:write",),
                default_latency_ms=800,
            ),
            ToolSpec(
                name="mail.list",
                description="List newest messages in the inbox.",
                permissions=("mail:read",),
            ),
            ToolSpec(
                name="mail.open",
                description="Open a specific email body.",
                permissions=("mail:read",),
            ),
            ToolSpec(
                name="mail.reply",
                description="Reply to an existing email thread.",
                side_effects=("mail_outbound", "event_schedule"),
                permissions=("mail:write",),
                default_latency_ms=800,
            ),
            ToolSpec(
                name="browser.read",
                description="Read current browser node.",
                permissions=("browser:read",),
            ),
            ToolSpec(
                name="browser.click",
                description="Click a UI element and navigate.",
                side_effects=("browser_navigation",),
                permissions=("browser:write",),
            ),
            ToolSpec(
                name="browser.find",
                description="Search current document for affordances.",
                permissions=("browser:read",),
            ),
            ToolSpec(
                name="browser.open",
                description="Open a URL inside the virtual browser.",
                side_effects=("browser_navigation",),
                permissions=("browser:write",),
            ),
            ToolSpec(
                name="browser.back",
                description="Navigate back to the previous page.",
                side_effects=("browser_navigation",),
                permissions=("browser:write",),
            ),
            ToolSpec(
                name="browser.type",
                description="Type text into a field.",
                side_effects=("browser_input",),
                permissions=("browser:write",),
            ),
            ToolSpec(
                name="browser.submit",
                description="Submit a form.",
                side_effects=("browser_navigation",),
                permissions=("browser:write",),
            ),
        ]
        # ERP and CRM specs are registered lazily to avoid importing optional twins here.
        erp_specs = [
            ToolSpec(name="erp.create_po", description="Create a purchase order.", permissions=("erp:write",)),
            ToolSpec(name="erp.get_po", description="Retrieve a purchase order.", permissions=("erp:read",)),
            ToolSpec(name="erp.list_pos", description="List purchase orders.", permissions=("erp:read",)),
            ToolSpec(name="erp.receive_goods", description="Record goods receipt.", permissions=("erp:write",)),
            ToolSpec(name="erp.submit_invoice", description="Submit a vendor invoice.", permissions=("erp:write",)),
            ToolSpec(name="erp.get_invoice", description="Retrieve invoice detail.", permissions=("erp:read",)),
            ToolSpec(name="erp.list_invoices", description="List invoices.", permissions=("erp:read",)),
            ToolSpec(name="erp.match_three_way", description="Run three-way match.", permissions=("erp:write",)),
            ToolSpec(name="erp.post_payment", description="Post a payment.", permissions=("erp:write",)),
        ]
        crm_specs = [
            ToolSpec(name="crm.create_contact", description="Create a CRM contact.", permissions=("crm:write",)),
            ToolSpec(name="crm.get_contact", description="Fetch CRM contact details.", permissions=("crm:read",)),
            ToolSpec(name="crm.list_contacts", description="List contacts.", permissions=("crm:read",)),
            ToolSpec(name="crm.create_company", description="Create a company record.", permissions=("crm:write",)),
            ToolSpec(name="crm.get_company", description="Fetch company details.", permissions=("crm:read",)),
            ToolSpec(name="crm.list_companies", description="List company records.", permissions=("crm:read",)),
            ToolSpec(name="crm.associate_contact_company", description="Link contact to company.", permissions=("crm:write",)),
            ToolSpec(name="crm.create_deal", description="Create a deal/opportunity.", permissions=("crm:write",)),
            ToolSpec(name="crm.get_deal", description="Fetch deal details.", permissions=("crm:read",)),
            ToolSpec(name="crm.list_deals", description="List deals.", permissions=("crm:read",)),
            ToolSpec(name="crm.update_deal_stage", description="Update deal stage.", permissions=("crm:write",)),
            ToolSpec(name="crm.log_activity", description="Log an activity.", permissions=("crm:write",)),
        ]
        specs.extend(erp_specs)
        specs.extend(crm_specs)
        for spec in specs:
            try:
                self.registry.register(spec)
            except ValueError:
                # Allow duplicate registration attempts when multiple routers spin up in tests.
                continue

    def last_receipt(self) -> Optional[Dict[str, Any]]:
        return self._receipts[-1] if self._receipts else None

    def call_and_step(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call, deliver any due event, advance time, and persist trace.

        This keeps the simulation deterministic and ensures artifacts are flushed
        so downstream scoring can consume trace.jsonl during tests.
        """
        result = self._execute(tool, args)
        self._record_tool_call(tool, args, result)
        self.trace.record_call(tool, args, result, time_ms=self.bus.clock_ms)
        evt = self.bus.next_if_due()
        if evt:
            emitted = None
            if evt.target == "slack":
                emitted = self.slack.deliver(evt.payload)
            elif evt.target == "mail":
                emitted = self.mail.deliver(evt.payload)
            if emitted is None:
                emitted = {}
            self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
            self._record_event_delivery(evt.target, evt.payload)
        self.bus.advance(1000)
        # Persist after each step when artifacts directory is configured
        self.trace.flush()
        return result

    def _execute(self, tool: str, args: Dict[str, Any]) -> Any:
        if tool == "slack.list_channels":
            return self.slack.list_channels()
        if tool == "slack.open_channel":
            return self.slack.open_channel(**args)
        if tool == "slack.send_message":
            return self.slack.send_message(**args)
        if tool == "slack.react":
            return self.slack.react(**args)
        if tool == "slack.fetch_thread":
            return self.slack.fetch_thread(**args)

        if tool == "mail.list":
            return self.mail.list(**args)
        if tool == "mail.open":
            return self.mail.open(**args)
        if tool == "mail.compose":
            return self.mail.compose(**args)
        if tool == "mail.reply":
            return self.mail.reply(**args)

        if tool == "browser.open":
            return self.browser.open(**args)
        if tool == "browser.find":
            return self.browser.find(**args)
        if tool == "browser.click":
            return self.browser.click(**args)
        if tool == "browser.type":
            return self.browser.type(**args)
        if tool == "browser.submit":
            return self.browser.submit(**args)
        if tool == "browser.read":
            return self.browser.read()
        if tool == "browser.back":
            return self.browser.back()

        # ERP tools
        if tool.startswith("erp."):
            if not getattr(self, "erp", None):
                raise MCPError("unsupported_tool", "ERP twin not available")
            erp = getattr(self, "erp")
            if tool == "erp.create_po":
                return erp.create_po(**args)
            if tool == "erp.get_po":
                return erp.get_po(**args)
            if tool == "erp.list_pos":
                return erp.list_pos()
            if tool == "erp.receive_goods":
                return erp.receive_goods(**args)
            if tool == "erp.submit_invoice":
                return erp.submit_invoice(**args)
            if tool == "erp.get_invoice":
                return erp.get_invoice(**args)
            if tool == "erp.list_invoices":
                return erp.list_invoices()
            if tool == "erp.match_three_way":
                return erp.match_three_way(**args)
            if tool == "erp.post_payment":
                return erp.post_payment(**args)
            raise MCPError("unknown_tool", f"No such tool: {tool}")

        # CRM tools
        if tool.startswith("crm."):
            if not getattr(self, "crm", None):
                raise MCPError("unsupported_tool", "CRM twin not available")
            crm = getattr(self, "crm")
            if tool == "crm.create_contact":
                return crm.create_contact(**args)
            if tool == "crm.get_contact":
                return crm.get_contact(**args)
            if tool == "crm.list_contacts":
                return crm.list_contacts()
            if tool == "crm.create_company":
                return crm.create_company(**args)
            if tool == "crm.get_company":
                return crm.get_company(**args)
            if tool == "crm.list_companies":
                return crm.list_companies()
            if tool == "crm.associate_contact_company":
                return crm.associate_contact_company(**args)
            if tool == "crm.create_deal":
                return crm.create_deal(**args)
            if tool == "crm.get_deal":
                return crm.get_deal(**args)
            if tool == "crm.list_deals":
                return crm.list_deals()
            if tool == "crm.update_deal_stage":
                return crm.update_deal_stage(**args)
            if tool == "crm.log_activity":
                return crm.log_activity(**args)
            raise MCPError("unknown_tool", f"No such tool: {tool}")

        raise MCPError("unknown_tool", f"No such tool: {tool}")

    def snapshot_observation(self, focus_hint: Optional[str] = None) -> Observation:
        """Build an Observation without advancing time or delivering events.

        Useful for server adapters that need to return an observation after a
        call_and_step without mutating simulator state a second time.
        """
        focus = focus_hint or "browser"
        return Observation(
            time_ms=self.bus.clock_ms,
            focus=focus,
            summary=self._summary(focus),
            screenshot_ref=None,
            action_menu=self._action_menu(focus),
            pending_events={
                "slack": self.bus.pending_count("slack"),
                "mail": self.bus.pending_count("mail"),
            },
        )

    def step_and_observe(self, tool: str, args: Dict[str, Any]) -> Observation:
        """Execute a tool call with deterministic step, then return an observation snapshot."""
        self.call_and_step(tool, args)
        focus = "browser"
        if tool.startswith("slack."):
            focus = "slack"
        elif tool.startswith("mail."):
            focus = "mail"
        elif tool.startswith("erp."):
            focus = "erp"
        elif tool.startswith("crm."):
            focus = "crm"
        elif tool.startswith("browser."):
            focus = "browser"
        return self.snapshot_observation(focus)

    def act_and_observe(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call, advance deterministic time, and return both result and observation.

        This is a convenience for clients that want a single call semantics.
        """
        result = self.call_and_step(tool, args)
        # Choose focus consistent with action
        focus = "browser"
        if tool.startswith("slack."):
            focus = "slack"
        elif tool.startswith("mail."):
            focus = "mail"
        elif tool.startswith("erp."):
            focus = "erp"
        elif tool.startswith("crm."):
            focus = "crm"
        obs = self.snapshot_observation(focus)
        return {"result": result, "observation": obs.model_dump()}

    def pending(self) -> Dict[str, int]:
        """Return pending event counts per target without advancing time."""
        return {
            "slack": self.bus.pending_count("slack"),
            "mail": self.bus.pending_count("mail"),
            "total": self.bus.pending_count(),
        }

    def tick(self, dt_ms: int = 1000) -> Dict[str, Any]:
        """Advance logical time by dt_ms and deliver all due events deterministically.

        Returns the number of delivered events per target and the new time.
        """
        delivered = {"slack": 0, "mail": 0}
        target_time = self.bus.clock_ms + max(0, int(dt_ms))
        # Deliver in order at due timestamps
        while (self.bus.peek_due_time() is not None) and (self.bus.peek_due_time() <= target_time):
            next_due = int(self.bus.peek_due_time() or self.bus.clock_ms)
            # advance clock to the event due time
            self.bus.clock_ms = next_due
            evt = self.bus.next_if_due()
            if evt:
                emitted = None
                if evt.target == "slack":
                    emitted = self.slack.deliver(evt.payload)
                elif evt.target == "mail":
                    emitted = self.mail.deliver(evt.payload)
                delivered[evt.target] += 1
                if emitted is None:
                    emitted = {}
                self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
                self._record_event_delivery(evt.target, evt.payload)
        # Advance remaining time to target_time
        self.bus.clock_ms = target_time
        self.trace.flush()
        return {"delivered": delivered, "time_ms": self.bus.clock_ms, "pending": self.pending()}

    def observe(self, focus_hint: Optional[str] = None) -> Observation:
        """Produce an observation and drain time/event queue incrementally.

        Unlike a pure read, observation advances logical time and delivers at
        most one due event to allow tests to "tick" the simulation forward
        without invoking a side-effecting tool.
        """
        # Deliver one due event if any
        evt = self.bus.next_if_due()
        if evt:
            emitted = None
            if evt.target == "slack":
                emitted = self.slack.deliver(evt.payload)
            elif evt.target == "mail":
                emitted = self.mail.deliver(evt.payload)
            if emitted is None:
                emitted = {}
            self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
            self._record_event_delivery(evt.target, evt.payload)
        # Advance time per observation to make future events become due
        self.bus.advance(1000)
        focus = focus_hint or "browser"
        obs = Observation(
            time_ms=self.bus.clock_ms,
            focus=focus,
            summary=self._summary(focus),
            screenshot_ref=None,
            action_menu=self._action_menu(focus),
            pending_events={
                "slack": self.bus.pending_count("slack"),
                "mail": self.bus.pending_count("mail"),
            },
        )
        # Persist observations/events so trace is available while running
        self.trace.flush()
        return obs

    def _summary(self, focus: str) -> str:
        if focus == "browser":
            r = self.browser.read()
            return f"Browser: {r['title']} — {r['excerpt']}"
        if focus == "slack":
            ch = self.slack.open_channel("#procurement")
            latest = ch["messages"][-1]["text"] if ch["messages"] else ""
            return f"Slack #procurement latest: {latest}"
        if focus == "mail":
            lst = self.mail.list()
            if lst:
                return f"Mail: {lst[0]['subj']} from {lst[0]['from']}"
            return "Mail: INBOX empty"
        if focus == "erp":
            # Surface a short state summary for agents
            pos = len(getattr(self, "erp").pos) if getattr(self, "erp", None) else 0
            invs = len(getattr(self, "erp").invoices) if getattr(self, "erp", None) else 0
            return f"ERP: {pos} POs, {invs} invoices"
        if focus == "crm":
            cs = len(getattr(self, "crm").contacts) if getattr(self, "crm", None) else 0
            ds = len(getattr(self, "crm").deals) if getattr(self, "crm", None) else 0
            return f"CRM: {cs} contacts, {ds} deals"
        return ""

    def _action_menu(self, focus: str) -> List[Dict[str, Any]]:
        if focus == "browser":
            node_aff = self.browser.nodes[self.browser.state]["affordances"]
            # Provide both concrete affordances and generic actions with schemas for LLMs
            generic: List[Dict[str, Any]] = [
                {"tool": "browser.read", "args_schema": {}},
                {"tool": "browser.find", "args_schema": {"query": "str", "top_k": "int?"}},
                {"tool": "browser.open", "args_schema": {"url": "str"}},
                {"tool": "browser.back", "args_schema": {}},
            ]
            return [*node_aff, *generic]
        if focus == "slack":
            return [
                {"tool": "slack.send_message", "args_schema": {"channel": "str", "text": "str", "thread_ts": "str?"}},
            ]
        if focus == "mail":
            return [
                {"tool": "mail.compose", "args_schema": {"to": "str", "subj": "str", "body_text": "str"}},
            ]
        if focus == "erp" and getattr(self, "erp", None):
            return [
                {"tool": "erp.create_po", "args_schema": {"vendor": "str", "currency": "str", "lines": "[{item_id,desc,qty,unit_price}]"}},
                {"tool": "erp.list_pos", "args_schema": {}},
                {"tool": "erp.submit_invoice", "args_schema": {"vendor": "str", "po_id": "str", "lines": "[{item_id,qty,unit_price}]"}},
                {"tool": "erp.match_three_way", "args_schema": {"po_id": "str", "invoice_id": "str", "receipt_id": "str?"}},
            ]
        if focus == "crm" and getattr(self, "crm", None):
            return [
                {"tool": "crm.create_contact", "args_schema": {"email": "str", "first_name": "str?", "last_name": "str?", "do_not_contact": "bool?"}},
                {"tool": "crm.create_company", "args_schema": {"name": "str", "domain": "str?"}},
                {"tool": "crm.associate_contact_company", "args_schema": {"contact_id": "str", "company_id": "str"}},
                {"tool": "crm.create_deal", "args_schema": {"name": "str", "amount": "number", "stage": "str?", "contact_id": "str?", "company_id": "str?"}},
                {"tool": "crm.update_deal_stage", "args_schema": {"id": "str", "stage": "str"}},
                {"tool": "crm.log_activity", "args_schema": {"kind": "str", "contact_id": "str?", "deal_id": "str?", "note": "str?"}},
            ]
        return []
